package __PACKAGE__;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class DeviceParser {
    private static final Map<String,Object> SPEC = map(Json.parse("__SPEC_JSON_JAVA__"));
    private static final Object MISSING = new Object();
    private DeviceParser() {}

    public static Map<String,Object> parse(Object payload, Map<String,Object> context) {
        if (payload instanceof byte[] bytes) return binary(bytes);
        if (payload instanceof Map<?,?> input && input.containsKey("registers")) return modbus(map(input));
        if (payload instanceof Map<?,?> input) return jsonPayload(map(input));
        if (payload instanceof String text) {
            String value = text.trim();
            if (value.startsWith("{") || value.startsWith("[")) {
                try { return jsonPayload(Json.parse(value)); }
                catch (RuntimeException ex) { return result(null,"failed",List.of(),List.of(),List.of(diag("FIELD_TYPE_MISMATCH","JSON 载荷无效","actual",ex.getMessage()))); }
            }
            String compact = value.replaceAll("\\s+", "");
            if ((compact.length() & 1) == 1 || !compact.matches("[0-9A-Fa-f]*")) return result(null,"failed",List.of(),List.of(),List.of(diag("INVALID_HEX","HEX 含非法字符或长度为奇数")));
            byte[] bytes = new byte[compact.length()/2];
            for (int i=0;i<bytes.length;i++) bytes[i]=(byte)Integer.parseInt(compact.substring(i*2,i*2+2),16);
            return binary(bytes);
        }
        return result(null,"failed",List.of(),List.of(),List.of(diag("FIELD_TYPE_MISMATCH","不支持的输入类型")));
    }

    public static Map<String,Object> parse(Object payload) { return parse(payload, Map.of()); }

    private static Map<String,Object> binary(byte[] payload) {
        if (payload.length > integer(SPEC.get("maxPayloadBytes"))) return result(null,"failed",List.of(),List.of(),List.of(diag("PAYLOAD_TOO_LARGE","载荷超过规则上限","actual",payload.length)));
        Map<String,Object> message = findMessage("binary", payload);
        if (message == null) return result(null,"failed",List.of(),List.of(),List.of(diag("UNKNOWN_MESSAGE","无法识别消息类型")));
        Map<String,Object> length = optMap(message.get("length"));
        if (length.containsKey("exact") && payload.length < integer(length.get("exact"))) return result(string(message.get("id")),"failed",List.of(),List.of(),List.of(diag("FRAME_TRUNCATED","报文长度不足","expected",integer(length.get("exact")),"actual",payload.length,"byteOffset",payload.length)));
        Map<String,Object> checksum = optMap(message.get("checksum"));
        if (!checksum.isEmpty()) {
            if (!"xor8".equals(checksum.get("algorithm"))) return result(string(message.get("id")),"failed",List.of(),List.of(),List.of(diag("CHECKSUM_UNSUPPORTED","未支持的强制校验算法","actual",checksum.get("algorithm"))));
            int value=integer(checksum.get("initial"));
            for(int i=integer(checksum.get("start"));i<integer(checksum.get("endExclusive"));i++) value ^= payload[i]&255;
            int position=integer(checksum.get("position")), actual=payload[position]&255;
            if(value!=actual) return result(string(message.get("id")),"failed",List.of(),List.of(),List.of(diag("CHECKSUM_MISMATCH","校验值不匹配","byteOffset",position,"expected",value,"actual",actual)));
        }
        List<Object> properties=new ArrayList<>(), warnings=new ArrayList<>();
        for(Object item:list(message.get("fields"))) {
            Map<String,Object> field=map(item), selector=map(field.get("selector")); int start=integer(selector.get("offset")), len=integer(selector.get("length"));
            if(start+len>payload.length) return result(string(message.get("id")),"failed",List.of(),List.of(),List.of(diag("FRAME_TRUNCATED","字段数据不完整","byteOffset",payload.length,"expected",start+len,"actual",payload.length)));
            byte[] chunk=Arrays.copyOfRange(payload,start,start+len); Object raw;
            if("float32".equals(field.get("type"))) {
                float f=ByteBuffer.wrap(chunk).order("little".equals(field.get("byteOrder"))?ByteOrder.LITTLE_ENDIAN:ByteOrder.BIG_ENDIAN).getFloat();
                if(!Float.isFinite(f)){ warnings.add(diag("NON_FINITE_NUMBER","浮点字段不是有限数","byteOffset",start)); raw=null; } else raw=new BigDecimal(Float.toString(f));
            } else {
                long value=0; if("little".equals(field.get("byteOrder"))) for(int i=chunk.length-1;i>=0;i--) value=(value<<8)|(chunk[i]&255); else for(byte b:chunk)value=(value<<8)|(b&255);
                boolean signed=string(field.get("type")).startsWith("int") || Boolean.TRUE.equals(field.get("signed"));
                if(signed && chunk.length<8 && (value & (1L<<(chunk.length*8-1)))!=0) value-=1L<<(chunk.length*8);
                if("bits".equals(field.get("type"))) value=(value>>integer(selector.get("bitOffset")))&((1L<<integer(selector.get("bitLength")))-1);
                raw=value;
            }
            properties.add(property(field,raw,warnings));
        }
        return result(string(message.get("id")),warnings.isEmpty()?"success":"partial",properties,warnings,List.of());
    }

    private static Map<String,Object> jsonPayload(Object payload) {
        Map<String,Object> message=findMessage("json",payload);
        if(message==null)return result(null,"failed",List.of(),List.of(),List.of(diag("UNKNOWN_MESSAGE","无法识别 JSON 消息类型")));
        List<Object> properties=new ArrayList<>(),warnings=new ArrayList<>(),errors=new ArrayList<>();
        for(Object item:list(message.get("fields"))) {
            Map<String,Object> field=map(item), selector=map(field.get("selector")); Object raw;
            if(selector.containsKey("collectionPath")) {
                Object items=path(payload,string(selector.get("collectionPath"))); List<Object> matches=new ArrayList<>();
                if(items instanceof List<?> values) for(Object entry:values) if(entry instanceof Map<?,?> m && Objects.equals(m.get(string(selector.get("matchKey"))),selector.get("matchValue"))) matches.add(entry);
                if(matches.size()>1)warnings.add(diag("DUPLICATE_JSON_FIELD","数组字段标识重复","jsonPath",selector.get("collectionPath")));
                raw=matches.isEmpty()?MISSING:map(matches.get(0)).getOrDefault(string(selector.getOrDefault("valueKey","value")),MISSING);
            } else raw=path(payload,string(selector.getOrDefault("path","$")));
            if(raw==MISSING){ (Boolean.TRUE.equals(field.get("required")) && "error".equals(field.getOrDefault("missing","error"))?errors:warnings).add(diag("FIELD_MISSING","字段缺失","jsonPath",selector.getOrDefault("path",selector.getOrDefault("collectionPath","$")))); continue; }
            String expected=string(field.get("type")); boolean good=("string".equals(expected)&&raw instanceof String)||("boolean".equals(expected)&&raw instanceof Boolean)||("integer".equals(expected)&&raw instanceof Long)||("number".equals(expected)&&raw instanceof Number);
            if(!good){warnings.add(diag("FIELD_TYPE_MISMATCH","JSON 字段类型不匹配","expected",expected,"actual",raw==null?"null":raw.getClass().getSimpleName()));continue;}
            properties.add(property(field,raw,warnings));
        }
        String status=!errors.isEmpty()?"failed":!warnings.isEmpty()?"partial":"success";
        return result(string(message.get("id")),status,"failed".equals(status)?List.of():properties,warnings,errors);
    }

    private static Map<String,Object> modbus(Map<String,Object> payload) {
        Object regsValue=payload.get("registers"), startValue=payload.get("startAddress");
        if(!(regsValue instanceof List<?>)||!(startValue instanceof Number))return result(null,"failed",List.of(),List.of(),List.of(diag("REGISTER_VALUE_INVALID","寄存器输入无效")));
        List<Object> registers=list(regsValue); for(Object value:registers)if(!(value instanceof Number)||integer(value)<0||integer(value)>65535)return result(null,"failed",List.of(),List.of(),List.of(diag("REGISTER_VALUE_INVALID","寄存器输入无效")));
        int start=integer(startValue); Map<String,Object> message=findMessage("modbus",payload);
        if(message==null)return result(null,"failed",List.of(),List.of(),List.of(diag("UNKNOWN_MESSAGE","无法识别 Modbus 消息类型")));
        List<Object> properties=new ArrayList<>(),warnings=new ArrayList<>(),errors=new ArrayList<>();
        for(Object item:list(message.get("fields"))) {
            Map<String,Object> field=map(item),selector=map(field.get("selector"));int address=integer(selector.get("address")),count=integer(selector.getOrDefault("registerCount",1)),index=address-start;
            if(index<0||index+count>registers.size()){int missing=index<0?address:start+registers.size();(Boolean.TRUE.equals(field.get("required"))?errors:warnings).add(diag("REGISTER_MISSING","寄存器块不完整","registerAddress",missing));continue;}
            List<Object> words=new ArrayList<>(registers.subList(index,index+count));if(count==2&&"low-first".equals(field.get("wordOrder")))Collections.reverse(words);
            ByteBuffer buffer=ByteBuffer.allocate(count*2).order(ByteOrder.BIG_ENDIAN);for(Object word:words)buffer.putShort((short)integer(word));Object raw;
            if("float32".equals(field.get("type"))){float f=ByteBuffer.wrap(buffer.array()).getFloat();if(!Float.isFinite(f)){warnings.add(diag("NON_FINITE_NUMBER","浮点字段不是有限数","registerAddress",address));raw=null;}else raw=new BigDecimal(Float.toString(f));}
            else {long value=0;for(byte b:buffer.array())value=(value<<8)|(b&255);raw=value;}
            properties.add(property(field,raw,warnings));
        }
        String status=!errors.isEmpty()?"failed":!warnings.isEmpty()?"partial":"success";return result(string(message.get("id")),status,"failed".equals(status)?List.of():properties,warnings,errors);
    }

    public static Map<String,Object> mapResult(Map<String,Object> result, Map<String,Object> context) {
        Map<String,Object> byCode=new LinkedHashMap<>(); for(Object item:list(result.get("properties"))){Map<String,Object> property=map(item);byCode.put(string(property.get("code")),property);}
        Map<String,Object> output=new LinkedHashMap<>();
        for(Object item:list(SPEC.get("mappings"))){Map<String,Object> mapping=map(item);Object source;
            if(mapping.get("contextSource")!=null)source=context.get(string(mapping.get("contextSource")));else {Object property=byCode.get(string(mapping.get("source")));source=property==null?null:map(property).get("value");}
            if(source==null&&Boolean.TRUE.equals(mapping.get("required"))){Map<String,Object> failed=new LinkedHashMap<>();failed.put("ok",false);failed.put("error",diag("MAPPING_REQUIRED_MISSING","目标映射缺少必填来源","actual",mapping.get("source")));return failed;}
            if(source==null&&"omit".equals(mapping.get("missing")))continue;Map<String,Object> cursor=output;String[] parts=string(mapping.get("targetPath")).split("\\.");
            for(int i=0;i<parts.length-1;i++){Object child=cursor.get(parts[i]);if(!(child instanceof Map<?,?>)){child=new LinkedHashMap<String,Object>();cursor.put(parts[i],child);}cursor=map(child);}cursor.put(parts[parts.length-1],source);
        }
        Map<String,Object> success=new LinkedHashMap<>();success.put("ok",true);success.put("data",output);return success;
    }

    private static Map<String,Object> findMessage(String kind,Object payload){for(Object item:list(SPEC.get("messages"))){Map<String,Object> message=map(item);if(!kind.equals(message.get("inputType")))continue;Map<String,Object> match=optMap(message.get("match"));if(match.isEmpty())return message;if("binary".equals(kind)){byte[] data=(byte[])payload,expected=hex(string(match.get("bytes")));int off=integer(match.getOrDefault("offset",0));if(off+expected.length<=data.length){boolean ok=true;for(int i=0;i<expected.length;i++)ok&=data[off+i]==expected[i];if(ok)return message;}}else if("json".equals(kind)&&Objects.equals(path(payload,string(match.getOrDefault("path","$"))),match.get("equals")))return message;else if("modbus".equals(kind)&&Objects.equals(match.getOrDefault("registerType",map(payload).get("registerType")),map(payload).get("registerType")))return message;}return null;}
    private static Object path(Object root,String path){Object value=root;if("$".equals(path)||path.isEmpty())return value;String clean=path.startsWith("$.")?path.substring(2):path;for(String part:clean.split("\\.")){if(value instanceof Map<?,?> m&&m.containsKey(part))value=m.get(part);else if(value instanceof List<?> l&&part.matches("\\d+")&&Integer.parseInt(part)<l.size())value=l.get(Integer.parseInt(part));else return MISSING;}return value;}
    private static Map<String,Object> property(Map<String,Object> field,Object raw,List<Object>warnings){Object value=raw;if(list(field.get("sentinels")).contains(raw)){warnings.add(diag("FIELD_SENTINEL","字段原始值为无效哨兵"));value=null;}else if(field.get("scale")==null){warnings.add(diag("FIELD_SCALE_UNKNOWN","字段倍率未知"));value=null;}else if(raw instanceof Number n){BigDecimal calculated=new BigDecimal(n.toString()).multiply(new BigDecimal(string(field.get("scale")))).add(new BigDecimal(string(field.getOrDefault("offset","0"))));value=calculated.stripTrailingZeros().scale()<=0?calculated.longValueExact():calculated.stripTrailingZeros();}if("unknown".equals(field.get("unitStatus")))warnings.add(diag("FIELD_UNIT_UNKNOWN","字段单位未知"));Map<String,Object> out=new LinkedHashMap<>();out.put("code",field.get("code"));out.put("rawValue",raw);out.put("value",value);out.put("unit",field.get("unit"));return out;}
    private static Map<String,Object> result(String message,String status,List<Object>properties,List<Object>warnings,List<Object>errors){Map<String,Object> out=new LinkedHashMap<>();out.put("protocolId",SPEC.get("protocolId"));out.put("protocolVersion",SPEC.get("protocolVersion"));out.put("messageType",message);out.put("parseStatus",status);out.put("properties",properties);out.put("warnings",warnings);out.put("errors",errors);return out;}
    private static Map<String,Object> diag(String code,String message,Object...values){Map<String,Object> out=new LinkedHashMap<>();out.put("code",code);out.put("message",message);for(int i=0;i<values.length;i+=2)out.put(string(values[i]),values[i+1]);return out;}
    private static byte[] hex(String text){byte[] out=new byte[text.length()/2];for(int i=0;i<out.length;i++)out[i]=(byte)Integer.parseInt(text.substring(i*2,i*2+2),16);return out;}
    @SuppressWarnings("unchecked") private static Map<String,Object> map(Object value){return (Map<String,Object>)value;}
    private static Map<String,Object> optMap(Object value){return value instanceof Map<?,?>?map(value):Map.of();}
    @SuppressWarnings("unchecked") private static List<Object> list(Object value){return value instanceof List<?>?(List<Object>)value:List.of();}
    private static int integer(Object value){return ((Number)value).intValue();} private static String string(Object value){return String.valueOf(value);}
    public static String toJson(Object value){return Json.write(value);}

    static final class Json {
        private final String text; private int pos; private Json(String text){this.text=text;}
        static Object parse(String text){Json parser=new Json(text);Object value=parser.value();parser.ws();if(parser.pos!=text.length())throw new IllegalArgumentException("JSON 尾部有多余字符");return value;}
        private Object value(){ws();if(pos>=text.length())throw new IllegalArgumentException("JSON 意外结束");char c=text.charAt(pos);if(c=='{')return object();if(c=='[')return array();if(c=='\"')return stringValue();if(c=='t'&&take("true"))return true;if(c=='f'&&take("false"))return false;if(c=='n'&&take("null"))return null;return number();}
        private Map<String,Object> object(){pos++;Map<String,Object> out=new LinkedHashMap<>();ws();if(peek('}')){pos++;return out;}while(true){String key=stringValue();ws();expect(':');out.put(key,value());ws();if(peek('}')){pos++;return out;}expect(',');}}
        private List<Object> array(){pos++;List<Object> out=new ArrayList<>();ws();if(peek(']')){pos++;return out;}while(true){out.add(value());ws();if(peek(']')){pos++;return out;}expect(',');}}
        private String stringValue(){ws();expect('\"');StringBuilder out=new StringBuilder();while(pos<text.length()){char c=text.charAt(pos++);if(c=='\"')return out.toString();if(c=='\\'){char e=text.charAt(pos++);if(e=='u'){out.append((char)Integer.parseInt(text.substring(pos,pos+4),16));pos+=4;}else out.append(switch(e){case 'n'->'\n';case 'r'->'\r';case 't'->'\t';case 'b'->'\b';case 'f'->'\f';default->e;});}else out.append(c);}throw new IllegalArgumentException("字符串未结束");}
        private Number number(){int start=pos;if(peek('-'))pos++;while(pos<text.length()&&Character.isDigit(text.charAt(pos)))pos++;boolean decimal=false;if(peek('.')){decimal=true;pos++;while(pos<text.length()&&Character.isDigit(text.charAt(pos)))pos++;}if(pos<text.length()&&(text.charAt(pos)=='e'||text.charAt(pos)=='E')){decimal=true;pos++;if(peek('+')||peek('-'))pos++;while(pos<text.length()&&Character.isDigit(text.charAt(pos)))pos++;}String value=text.substring(start,pos);return decimal?new BigDecimal(value):Long.valueOf(value);}
        private boolean take(String value){if(text.startsWith(value,pos)){pos+=value.length();return true;}return false;}private void expect(char c){ws();if(!peek(c))throw new IllegalArgumentException("期望 "+c);pos++;}private boolean peek(char c){return pos<text.length()&&text.charAt(pos)==c;}private void ws(){while(pos<text.length()&&Character.isWhitespace(text.charAt(pos)))pos++;}
        static String write(Object value){if(value==null)return"null";if(value instanceof String s)return"\""+escape(s)+"\"";if(value instanceof Boolean||value instanceof Number)return value instanceof BigDecimal b?b.stripTrailingZeros().toPlainString():value.toString();if(value instanceof Map<?,?> m){StringJoiner join=new StringJoiner(",","{","}");for(var e:m.entrySet())join.add(write(String.valueOf(e.getKey()))+":"+write(e.getValue()));return join.toString();}if(value instanceof Iterable<?> items){StringJoiner join=new StringJoiner(",","[","]");for(Object item:items)join.add(write(item));return join.toString();}throw new IllegalArgumentException("不能序列化 "+value.getClass());}private static String escape(String value){return value.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r").replace("\t","\\t");}
    }
}
