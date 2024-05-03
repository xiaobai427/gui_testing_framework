# coding: utf-8

import os
import sys
import shutil
import argparse
from xml.etree import ElementTree as etree
from configparser import ConfigParser
from .app import TestAgent
from ..constants import PACKAGE_NAME
from ..environment import WorkEnv

AGENT_WIN32_SERVICE_BASENAME = 'agent.xml'
AGENT_LINUX_SERVICE_BASENAME = 'agent.service'

PROG = f"python -m {PACKAGE_NAME}.agent"


def main():
    print(f"cwd: {os.getcwd()}")
    print(f"sys.argv: {sys.argv}")
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)

    parser.add_argument('-w', '--work-dir', dest="work_dir")
    parser.add_argument('--agent-yml', help='agent yaml')
    parser.add_argument('--bench-yml', help='bench yaml')
    parser.add_argument('--trace-yml', help='trace yaml')

    sub_parsers = parser.add_subparsers(dest="func")
    init_sub_parser = sub_parsers.add_parser("srv", help='install agent as service')
    init_sub_parser.add_argument('--name', help='service name')
    init_sub_parser.add_argument('--description', help='service description')

    sub_parsers.add_parser("run", help=f'run test agent, detail: {PROG} run -h')

    args = parser.parse_args()
    work_env = WorkEnv.instance(args.work_dir)
    work_dir = work_env.work_dir
    if not work_dir:
        msg = f"No '--work-dir' argument provided, and can't find '.{PACKAGE_NAME}' from cwd and its ancestor dirs."
        raise ValueError(msg)

    print(f"sys.path: {sys.path}")
    bin_dir = work_dir.joinpath("bin")

    if args.func == 'run':
        print("change cwd to: %s" % bin_dir)
        os.chdir(bin_dir)       # to make sure relative path can work in conf file.
        agent = TestAgent(work_env, args.agent_yml, args.bench_yml, args.trace_yml)
        agent.startup()
    elif args.func == 'srv':
        service_name = args.name
        service_desp = args.description
        if sys.platform == 'win32':
            filename = bin_dir.joinpath('agent.xml')
            root_element = etree.parse(filename)
            root_element.find('id').text = service_name
            root_element.find('name').text = service_name
            root_element.find('description').text = service_desp
            root_element.write(filename)

            os.system(f'cd {bin_dir} && agent.exe install')
        elif sys.platform.startswith('linux'):
            parser = ConfigParser()
            filename = bin_dir.joinpath(bin_dir, AGENT_LINUX_SERVICE_BASENAME)
            parser.read(filename)
            parser.set('Unit', 'Description', service_desp or service_name)
            parser.set('Service', 'WorkingDirectory', str(work_dir))
            with filename.open('w') as f:
                parser.write(f)

            shutil.copy2(filename, os.path.join('/etc/systemd/system', f'{service_name}.service'))
        else:
            pass


main()
