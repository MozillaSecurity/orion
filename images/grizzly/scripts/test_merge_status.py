import os
import shutil
import sys
import tempfile
import unittest

from merge_status import StatusReportMerger

class TestCase(unittest.TestCase):
    if sys.version_info.major == 2:
        def assertRegex(self, *args, **kwds):
            return self.assertRegexpMatches(*args, **kwds)
        def assertRaisesRegex(self, *args, **kwds):
            return self.assertRaisesRegexp(*args, **kwds)

#def make_report(target_dir):

StatusReportMerger.CPU_CHECK_INTERVAL = 0.01

class MergerTests(TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        fd, self.tmpfn = tempfile.mkstemp()
        os.close(fd)

    def tearDown(self):
        if os.path.isfile(self.tmpfn):
            os.unlink(self.tmpfn)
        if os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_1(self):
        "test no input files"
        srm = StatusReportMerger(self.tmpdir)
        # no report files
        srm.read_reports()
        srm.read_log_tracebacks()
        merged = os.path.join(self.tmpdir, "merged_report.txt")
        srm.dump_report(merged)
        self.assertTrue(os.path.isfile(merged))

    def test_2(self):
        "test empty input files"
        srm = StatusReportMerger(self.tmpdir)
        test_report = os.path.join(self.tmpdir, "grz_status_123.json")
        with open(test_report, "w") as test_fp:
            test_fp.write("{}")
        srm.read_reports()
        test_log_0 = os.path.join(self.tmpdir, "screenlog.0")
        with open(test_log_0, "w") as test_fp:
            test_fp.write("blah\nblah\n")
        test_log_1 = os.path.join(self.tmpdir, "screenlog.1")
        with open(test_log_1, "w") as test_fp:
            test_fp.write("")
        srm.read_log_tracebacks()
        merged = os.path.join(self.tmpdir, "merged_report.txt")
        srm.dump_report(merged)
        self.assertTrue(os.path.isfile(merged))

    def test_3(self):
        "test reading report files"
        srm = StatusReportMerger(self.tmpdir)
        test_report_1 = os.path.join(self.tmpdir, "grz_status_123.json")
        with open(test_report_1, "w") as test_fp:
            test_fp.write('{' \
                '"Ignored": 3, ' \
                '"Logsize": 1068576, ' \
                '"Rate": 0.9576351392099345, '\
                '"Iteration": 2329, ' \
                '"Results": 0}')
        test_report_2 = os.path.join(self.tmpdir, "grz_status_456.json")
        with open(test_report_2, "w") as test_fp:
            test_fp.write('{' \
                '"Iteration": 0, ' \
                '"Logsize": 466944, ' \
                '"Results": 0}')
        srm.read_reports()
        merged = os.path.join(self.tmpdir, "merged_report.txt")
        srm.dump_report(merged)
        self.assertTrue(os.path.isfile(merged))
        with open(merged, "r") as fp:
            merged_log = fp.read()
        self.assertRegex(merged_log, r"^Iterations:\s+\d+\s+\(")
        self.assertRegex(merged_log, r"\nRate:\s+\d+\.\d+\s+\(")
        self.assertRegex(merged_log, r"\nLogs:\s+\d+\.\d+MB\s+\(")
        self.assertRegex(merged_log, r"\nResults:\s+\d+")
        self.assertRegex(merged_log, r"\nIgnored:\s+\d+\s+\(")
        self.assertRegex(merged_log, r"\nTimestamp:\s+")
