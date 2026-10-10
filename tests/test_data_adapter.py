"""Synthetic attachments: expected energy/slot boundaries are independently specified."""
import copy
import csv
from datetime import datetime, time
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import copilot_data as data
from copilot_domain import seal_record


class DataAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = {"schema_version": "1.0", "question": "Q1", "source": {"path": "附件.csv"},
                     "columns": [{"name": "date", "source": "日期", "type": "date", "fill": "forward"},
                                 {"name": "time", "source": "时间", "type": "time"},
                                 {"name": "energy", "source": "功率", "type": "number", "unit": "kW", "output_unit": "kWh", "power_basis": "interval_mean", "min": 0}],
                     "time_axis": {"date_column": "date", "time_column": "time", "label": "end", "interval_minutes": 10, "start": "2026-01-01T00:00:00", "periods": 144}}
        self.rows = [["2026-01-01" if n == 1 else "", f"{n // 6}:{n % 6 * 10:02}" if n < 144 else "0:00+1", 60] for n in range(1, 145)]
        self.write_csv()
        self.write_spec()

    def write_csv(self, encoding="utf-8", header=None):
        with (self.root / "附件.csv").open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header or ["日期", "时间", "功率"])
            writer.writerows(self.rows)

    def write_spec(self):
        (self.root / "spec.json").write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")

    def parsed(self):
        self.write_spec()
        return data.normalize(self.root, data.read_spec(self.root, "spec.json"))

    def test_csv_energy_daily_total_cross_day_and_original_preserved(self):
        before = (self.root / "附件.csv").read_bytes()
        rows, report = self.parsed()
        self.assertEqual(len(rows), 144)
        self.assertEqual([row["energy"] for row in rows], [10.0] * 144)
        self.assertEqual(sum(row["energy"] for row in rows), 1440)
        self.assertEqual(rows[0]["slot_start"], "2026-01-01T00:00:00")
        self.assertEqual(rows[-1]["slot_end"], "2026-01-02T00:00:00")
        self.assertEqual(len(report["filled_dates"]), 143)
        result = data.prepare(self.root, "spec.json", "normalized/v1")
        contract = json.loads((self.root / result["contract"]).read_text(encoding="utf-8"))
        self.assertEqual(data.validate_adapter(self.root, contract), [])
        self.assertEqual((self.root / "附件.csv").read_bytes(), before)
        self.assertFalse(result["registered"])
        with self.assertRaisesRegex(data.DataError, "已存在"):
            data.prepare(self.root, "spec.json", "normalized/v1")

    def test_csv_gbk_must_be_declared(self):
        self.write_csv("gbk")
        with self.assertRaisesRegex(data.DataError, "编码"):
            self.parsed()
        self.spec["source"]["encoding"] = "gbk"
        self.assertEqual(len(self.parsed()[0]), 144)

    def test_missing_duplicate_out_of_order_and_shifted_slots_rejected(self):
        original = copy.deepcopy(self.rows)
        cases = [original[:-1], original[:5] + original[6:], original[:4] + [original[3]] + original[5:],
                 [original[1], original[0]] + original[2:]]
        for rows in cases:
            with self.subTest(rows=len(rows)):
                self.rows = rows
                self.write_csv()
                with self.assertRaises(data.DataError):
                    self.parsed()
        self.rows = original
        self.write_csv()
        self.spec["time_axis"]["label"] = "start"
        with self.assertRaisesRegex(data.DataError, "偏移"):
            self.parsed()

    def test_missing_measurement_nonfinite_and_negative_rejected(self):
        for value in ("", "NaN", "Inf", "-2", "unknown"):
            with self.subTest(value=value):
                self.rows[5][2] = value
                self.write_csv()
                with self.assertRaisesRegex(data.DataError, "第 7 行 功率"):
                    self.parsed()

    def test_explicit_null_is_preserved_not_zero(self):
        self.rows[5][2] = ""
        self.write_csv()
        self.spec["columns"][2]["nullable"] = True
        self.assertIsNone(self.parsed()[0][5]["energy"])

    def test_measurement_cannot_be_forward_filled(self):
        self.spec["columns"][2]["fill"] = "forward"
        with self.assertRaisesRegex(data.DataError, "只允许"):
            self.parsed()

    def test_units_must_be_explicit_and_conversion_supported(self):
        for unit in (None, "", "kilowatt"):
            with self.subTest(unit=unit):
                self.spec["columns"][2]["unit"] = unit
                with self.assertRaises(data.DataError):
                    self.parsed()
        self.spec["columns"][2]["unit"] = "kW"
        del self.spec["time_axis"]
        with self.assertRaisesRegex(data.DataError, "时长"):
            self.parsed()

    def test_instantaneous_power_is_not_assumed_to_be_interval_mean(self):
        del self.spec["columns"][2]["power_basis"]
        with self.assertRaisesRegex(data.DataError, "瞬时测量"):
            self.parsed()

    def test_misspelled_contract_fields_are_not_silently_ignored(self):
        self.spec["columns"][2]["output_unitt"] = "kWh"
        with self.assertRaisesRegex(data.DataError, "未知字段"):
            self.parsed()

    def test_headers_and_ragged_rows_rejected(self):
        self.write_csv(header=["日期", "功率", "功率"])
        with self.assertRaisesRegex(data.DataError, "重复"):
            self.parsed()
        self.rows[4].pop()
        self.write_csv()
        with self.assertRaisesRegex(data.DataError, "列数"):
            self.parsed()

    def test_simple_numeric_csv_unique_keys_and_integer_type(self):
        self.spec = {"schema_version": "1.0", "question": "Q2", "source": {"path": "附件.csv"},
                     "columns": [{"name": "id", "source": "id", "type": "integer", "unit": "1"},
                                 {"name": "mass", "source": "mass", "type": "number", "unit": "kg"}], "unique_keys": ["id"]}
        self.rows = [[1, 3], [2, 4]]
        self.write_csv(header=["id", "mass"])
        self.assertEqual(self.parsed()[0][1]["mass"], 4)
        self.rows[1][0] = 1
        self.write_csv(header=["id", "mass"])
        with self.assertRaisesRegex(data.DataError, "重复"):
            self.parsed()

    def test_report_or_normalized_tampering_is_replayed_not_trusted(self):
        result = data.prepare(self.root, "spec.json", "normalized/v1")
        contract = json.loads((self.root / result["contract"]).read_text(encoding="utf-8"))
        path = self.root / result["normalized"]
        path.write_text(path.read_text(encoding="utf-8").replace(",10.0,", ",99.0,", 1), encoding="utf-8")
        changed = data.binding(self.root, result["normalized"])
        contract["adapter"]["normalized"] = changed
        contract["inventory"]["entries"][2] = changed
        contract["inventory"] = seal_record(contract["inventory"])
        self.assertTrue(any("不一致" in e for e in data.validate_adapter(self.root, contract)))

    def test_large_integer_identifiers_keep_exact_digits(self):
        self.spec = {"schema_version": "1.0", "question": "Q1", "source": {"path": "附件.csv"},
                     "columns": [{"name": "id", "source": "id", "type": "integer", "unit": "1"}], "unique_keys": ["id"]}
        self.rows = [[9007199254740992], [9007199254740993]]
        self.write_csv(header=["id"])
        self.assertEqual([row["id"] for row in self.parsed()[0]], [9007199254740992, 9007199254740993])

    def test_write_readback_detects_cell_difference(self):
        rows, _ = self.parsed()
        target = self.root / "roundtrip.csv"
        target.write_bytes(data.csv_bytes(rows))
        rows[20]["energy"] = 100
        with self.assertRaisesRegex(data.DataError, "第 21 槽"):
            data.verify_csv(target, rows)

    def test_cli_success_and_error_exit(self):
        command = [sys.executable, str(ROOT / "scripts/copilot.py"), "--workspace", str(self.root), "data"]
        completed = subprocess.run(command + ["prepare", "--spec", "spec.json", "--output", "normalized/v1"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["result"]["row_count"], 144)
        failed = subprocess.run(command + ["prepare", "--spec", "spec.json", "--output", "normalized/v1"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(failed.returncode, 2)
        self.assertFalse(json.loads(failed.stderr)["ok"])

    def test_unsafe_path_rejected(self):
        self.spec["source"]["path"] = "../outside.csv"
        with self.assertRaisesRegex(data.DataError, "安全"):
            self.parsed()

    def xlsx(self, *, formula=False, unmerged_missing=False):
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = "每日数据"
        sheet.append(["日期", "时间", "功率"])
        for n in range(1, 145):
            clock = time(n // 6, n % 6 * 10) if n < 144 else "0:00+1"
            sheet.append([datetime(2026, 1, 1) if n == 1 else None, clock, "=30+30" if formula and n == 5 else 60])
        if not unmerged_missing:
            sheet.merge_cells("A2:A145")
        book.save(self.root / "附件.xlsx")
        book.close()
        self.spec["source"] = {"path": "附件.xlsx", "sheet": "每日数据"}
        self.spec["columns"][0]["fill"] = "merged"

    def test_xlsx_merged_dates_native_times_and_crossday(self):
        self.xlsx()
        rows, report = self.parsed()
        self.assertEqual(sum(r["energy"] for r in rows), 1440)
        self.assertEqual(report["locations"][8]["columns"]["date"], {"row": 2, "column": 1})
        self.assertEqual(rows[-1]["slot_end"], "2026-01-02T00:00:00")

    def test_xlsx_missing_formula_cache_is_not_zero(self):
        self.xlsx(formula=True)
        with self.assertRaisesRegex(data.DataError, "公式缺少缓存"):
            self.parsed()

    def test_xlsx_merged_policy_does_not_fill_unmerged_blanks(self):
        self.xlsx(unmerged_missing=True)
        with self.assertRaisesRegex(data.DataError, "缺失值"):
            self.parsed()


if __name__ == "__main__":
    unittest.main()
