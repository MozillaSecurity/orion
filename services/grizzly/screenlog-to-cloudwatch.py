#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path


LOG_PATH = Path("/home/worker/grizzly-auto-run")
CONF_PATH = Path("/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json")
POLL_INTERVAL = 30
AGENT_PATH = Path("/opt/aws/amazon-cloudwatch-agent/bin/start-amazon-cloudwatch-agent")


class LogWatcher(object):

    def __init__(self):
        self.agent = None
        self.watched = set()

    def run(self):
        try:
            while True:
                changed = False
                for log in LOG_PATH.glob("screenlog.*"):
                    if log not in self.watched:
                        changed = True
                        self.watched.add(log)
                if changed:
                    self.write_conf()
                    self.start_agent()

                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_agent()

    def start_agent(self):
        self.stop_agent()
        self.agent = subprocess.Popen(str(AGENT_PATH))

    def stop_agent(self):
        if self.agent is not None:
            self.agent.terminate()
            self.agent.wait()
            self.agent = None

    def write_conf(self):
        collect_list = []
        collect_template = {
            "file_path": "/home/user/grizzly-auto-run/screenlog.0",
            "log_group_name": "grizzly-{instance_id}",
            "log_stream_name": "screenlog.0",
            "timestamp_format": "%Y-%m-%d %H:%M:%S",
            "timezone": "UTC",
        }
        conf = {
            "agent": {
                "region": "us-east-2",
                "run_as_user": "cwagent",
            },
            "logs": {
                "logs_collected": {
                    "files": {
                        "collect_list": collect_list,
                    },
                },
                "log_stream_name": "default_af",
            },
        }
        for log_file in self.watched:
            collect_template["file_path"] = str(log_file.resolve())
            collect_template["log_stream_name"] = log_file.name
            collect_list.append(collect_template.copy())

        with CONF_PATH.open("w") as conf_fp:
            json.dump(conf, conf_fp)


def main():
    LogWatcher().run()


if __name__ == "__main__":
    main()
