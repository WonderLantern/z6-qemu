# SPDX-License-Identifier: GPL-2.0-or-later
"""Summarize observed counter timing. Never label timer events sensor exposure."""
import argparse
import json
from pathlib import Path


def summarize(text):
    runs, active, submissions, warnings = [], {}, [], []
    for line in text.splitlines():
        if 'Z6_COUNTER_TIMING ' in line:
            fields = dict(item.split('=', 1) for item in line.split('Z6_COUNTER_TIMING ', 1)[1].split() if '=' in item)
            ch, now = int(fields['channel']), int(fields['virtual_ns'])
            if fields['phase'] == 'start':
                if ch in active:
                    warnings.append(f'channel {ch} restarted before observed stop')
                run = {'channel': ch, 'start_ns': now, 'deadline_ns': int(fields['scheduled_ns']),
                       'initial': int(fields['initial'], 16), 'terminal': int(fields['terminal'], 16),
                       'tick_ns': int(fields['tick_ns']), 'tick_hypothesis': True,
                       'scope': 'counter only', 'events': [], 'completed': False}
                run['programmed_duration_ns'] = run['deadline_ns'] - now
                runs.append(run)
                active[ch] = run
            elif ch in active:
                run = active[ch]
                run['events'].append({'phase': fields['phase'], 'virtual_ns': now})
                if fields['phase'] == 'terminal':
                    run['completed'] = True
                    run.setdefault('first_terminal_ns', now)
                    run.setdefault('observed_duration_ns', now-run['start_ns'])
                    run['early_terminal'] = run.get('early_terminal', False) or now < run['deadline_ns']
                elif fields['phase'] == 'stop':
                    run['stop_ns'] = now
                    run['cancelled_before_terminal'] = not run['completed']
                    del active[ch]
            else:
                warnings.append(f'unmatched {fields["phase"]} on channel {ch}')
        elif 'Z6_EXPOSURE_MMIO ' in line:
            fields = dict(item.split('=', 1) for item in line.split('Z6_EXPOSURE_MMIO ', 1)[1].split() if '=' in item)
            if int(fields['addr'], 16) in (0x20061264, 0x20061268):
                submissions.append(fields)
        elif 'Z6_EXPOSURE_TRACE_LIMIT' in line:
            warnings.append('MMIO trace truncated; absence of later writes is not evidence')
    return {'counter_runs': runs, 'sensor_script_submissions': submissions,
            'warnings': warnings, 'physical_tick_verified': False,
            'sensor_integration_verified': False, 'firmware_capture_verified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.log.read_text(encoding='utf-8', errors='replace'))
    report['source_log'] = str(args.log)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'runs': len(report['counter_runs']), 'script_writes': len(report['sensor_script_submissions']),
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
