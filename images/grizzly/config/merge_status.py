#!/usr/bin/env python
# encoding: utf-8
import argparse
import json
import re
import os
import tempfile
import time
import traceback

try:
    import psutil
except ImportError:
    psutil = None

class StatusReportMerger(object):
    CPU_CHECK_INTERVAL = 1
    DISPLAY_LIMIT_LOG = 10 # don't include log results unless size exceeds 10MBs
    READ_BUF_SIZE = 0x10000 # 64KB

    def __init__(self, grizzly_path):
        self.grizzly_path = grizzly_path
        self.ignored = 0 # number if timeouts ignored
        self.iterations = list() # number of iterations per instances
        self.log_size = list() # browser log size
        self.rates = list() # iteration rate per instances
        self.results = 0 # results found
        self.tracebacks = list() # traceback lines from screen logs

    @staticmethod
    def _find_files(log_path, fname_pattern):
        file_list = list()
        if os.path.isdir(log_path):
            abs_path = os.path.abspath(log_path)
            for report_file in os.listdir(abs_path):
                if fname_pattern.match(report_file) is None:
                    continue
                report_file = os.path.join(abs_path, report_file)
                if os.path.isfile(report_file) and os.path.getsize(report_file) > 0:
                    file_list.append(report_file)
        return file_list

    def read_log_tracebacks(self, max_preceeding=5):
        # look for screen logs and scan for python tracebacks
        re_traceback = re.compile(r"Traceback \(most recent call last\):")
        re_tbline = re.compile(r"\s+")
        screen_logs = self._find_files(self.grizzly_path, re.compile(r"screenlog\.\d+"))
        for screen_log in screen_logs:
            try:
                log_data = None
                with open(screen_log, "r") as in_fp:
                    while True:
                        current_pos = in_fp.tell()
                        line_data = in_fp.readline()
                        if not line_data:
                            break
                        if re.match(re_traceback, line_data) is not None:
                            in_fp.seek(max(current_pos-4096, 0)) # seek 4kb before tb
                            log_data = in_fp.read(self.READ_BUF_SIZE)
                            break
            except IOError:
                continue # in case the file goes away
            if log_data is None:
                continue # no traceback here, move along
            tb_start = None
            tb_end = None
            log_data = log_data.splitlines()
            line_count = len(log_data)
            for num, log_line in enumerate(log_data):
                if tb_start is None and re.match(re_traceback, log_line) is not None:
                    tb_start = num
                elif tb_start is not None and re.match(re_tbline, log_line) is None:
                    tb_end = min(num + 1, line_count)
                    break
            if tb_start is None:
                self.tracebacks.append("PARSE ERROR: Failed to parse Traceback! (%s)" % screen_log)
                continue # this should not happen!
            tb_start = max(tb_start - max_preceeding, 0)
            if tb_end is None:
                tb_end = line_count
            self.tracebacks.append("Log: %r" % screen_log)
            self.tracebacks.extend(log_data[tb_start:tb_end])
            self.tracebacks.append("")

    def read_reports(self):
        for report_file in self._find_files(self.grizzly_path, re.compile(r"grz_status_\d+\.json")):
            try:
                with open(report_file, "r") as r_fp:
                    report = json.load(r_fp)
            except IOError:
                continue # in case the file goes away
            self.ignored += report.get("Ignored", 0)
            self.iterations.append(report.get("Iteration", 0))
            self.log_size.append(report.get("Logsize", 0))
            self.rates.append(report.get("Rate", 0))
            self.results += report.get("Results", 0)

    def dump_report(self, out_file):
        total_iters = sum(self.iterations)
        tmp_fd, merge_file = tempfile.mkstemp(suffix="_merge_log.txt")
        os.close(tmp_fd)
        with open(merge_file, "w") as out_fp:
            # Iterations
            out_fp.write("Iterations: %d" % total_iters)
            if len(self.iterations) > 1:
                out_fp.write(" (%s)" % ", ".join(["%d" % iters for iters in self.iterations]))
            out_fp.write("\n")
            # Rate
            out_fp.write("Rate:       %0.2f" % sum(self.rates))
            if len(self.rates) > 1:
                out_fp.write(" (%s)" % ", ".join(["%0.2f" % rate for rate in self.rates]))
            out_fp.write("\n")
            # Results
            out_fp.write("Results:    %d\n" % self.results)
            # Ignored
            if self.ignored > 0:
                out_fp.write("Ignored:    %d" % self.ignored)
                out_fp.write(" (%0.4f%%)" % (self.ignored/float(total_iters)))
                out_fp.write("\n")
            # Log size
            log_usage = sum(self.log_size)/1048576.0
            if log_usage > self.DISPLAY_LIMIT_LOG:
                out_fp.write("Logs:       %0.1fMB" % log_usage)
                if len(self.log_size) > 1:
                    out_fp.write(" (%s)" % (
                        ", ".join(["%0.1f" % (lsize/1048576.0) for lsize in self.log_size])))
                out_fp.write("\n")
            # dump system info if psutil is available
            if psutil is not None:
                out_fp.write("CPU & Load: %0.1f%% %s\n" % (
                    psutil.cpu_percent(interval=self.CPU_CHECK_INTERVAL), os.getloadavg()))
                out_fp.write("Memory:     %dMB available\n" % (
                    psutil.virtual_memory().available/1048576))
                out_fp.write("Disk:       %dMB available\n" % (
                    psutil.disk_usage("/").free/1048576))
            # dump timestamp
            out_fp.write("Timestamp:  %s" % (
                time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())))
            # dump tracebacks
            if self.tracebacks:
                out_fp.write("\n\nWARNING Tracebacks detected!\n")
                for trbk in self.tracebacks:
                    out_fp.write(trbk)
                    out_fp.write("\n")

        attempts = 2 # try to rename file 2x max
        while attempts > 0:
            attempts -= 1
            try:
                os.rename(merge_file, out_file)
                attempts = 0 # success
            except OSError:
                if attempts == 0:
                    raise
                time.sleep(2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("grizzly_path")
    parser.add_argument("outfile")
    args = parser.parse_args()

    try:
        srm = StatusReportMerger(args.grizzly_path)
        srm.read_reports()
        srm.read_log_tracebacks()
        srm.dump_report(args.outfile)
    except Exception: # pylint: disable=broad-except
        try:
            with open(args.outfile, "w") as out_fp:
                out_fp.write("Something is wrong!\n\n")
                out_fp.write(traceback.format_exc())
                out_fp.write("\n")
            raise
        except IOError:
            pass

if __name__ == "__main__":
    main()
