import unittest
from ripple_lab.network import link_commands


class NetworkTests(unittest.TestCase):
    def test_link_classifies_only_its_destination_and_byte_queue(self):
        commands = link_commands({"ip": "10.210.25.2"}, {"ip": "10.210.25.3"},
                                 {"bandwidth_kbit": 64, "delay_ms": 20, "loss_percent": 0,
                                  "queue_bytes": 8192}, 10)
        joined = "\n".join(" ".join(c) for c in commands)
        self.assertIn("64000bit", joined)
        self.assertIn("10.210.25.3/32", joined)
        self.assertNotIn("10.210.25.2/32", joined)
        self.assertIn("bfifo limit 8192", joined)
        self.assertIn("20ms", joined)


if __name__ == "__main__":
    unittest.main()
