import copy
import unittest
from ripple_lab.config import default_config, normalize_config


class ConfigTests(unittest.TestCase):
    def test_default_and_directional_links(self):
        value = default_config()
        value["links"] = [{"source": "s1", "target": "c1", "bandwidth_kbit": 64},
                          {"source": "c1", "target": "s1", "bandwidth_kbit": 256}]
        result = normalize_config(value)
        self.assertEqual([l["bandwidth_kbit"] for l in result["links"]], [64, 256])
        self.assertEqual(result["links"][0]["queue_bytes"], 1048576)

    def test_rejects_invalid_topology_and_numbers(self):
        for update in ({"wait_seconds": -1}, {"wait_seconds": float("nan")},
                       {"protocol": "invented"}, {"nodes": []}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                normalize_config(dict(default_config(), **update))
        value = default_config()
        value["nodes"][1]["server"] = "missing"
        with self.assertRaises(ValueError):
            normalize_config(value)

    def test_rejects_duplicate_direction_and_invalid_payload(self):
        value = default_config()
        value["links"] = [{"source": "s1", "target": "c1"}] * 2
        with self.assertRaises(ValueError):
            normalize_config(value)
        value = default_config()
        value["nodes"][1]["size"] = 1000000
        with self.assertRaises(ValueError):
            normalize_config(value)

    def test_multi_publishers_are_independent_and_input_unchanged(self):
        value = default_config()
        value["nodes"].append(dict(value["nodes"][1], id="p2", rate=3))
        before = copy.deepcopy(value)
        result = normalize_config(value)
        self.assertEqual(value, before)
        self.assertEqual(sum(n["role"] == "publisher" for n in result["nodes"]), 2)


if __name__ == "__main__":
    unittest.main()
