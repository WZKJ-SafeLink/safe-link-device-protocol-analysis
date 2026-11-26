import unittest
from protocol_parser import parse
class ParserTest(unittest.TestCase):
    def test_unknown(self): self.assertEqual("failed", parse("FF")["parseStatus"])
if __name__ == "__main__": unittest.main()
