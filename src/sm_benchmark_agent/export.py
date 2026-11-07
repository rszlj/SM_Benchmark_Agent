"""Export or verify an explicit anchor-year delivery plan. No remote calls."""
import argparse
import json
from pathlib import Path
from sm_benchmark_agent.delivery import export_anchor_year, export_gridded_archive, verify_delivery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--execute', action='store_true', help='Copy assets; default only validates the plan')
    parser.add_argument('--gridded-zip', action='store_true', help='Assemble explicitly station-free prepared assets into a ZIP')
    parser.add_argument('--verify', type=Path, help='Verify an already exported directory')
    args = parser.parse_args()
    if args.verify:
        if args.plan or args.output_root or args.execute or args.gridded_zip:
            parser.error('--verify cannot be combined with export options')
        result = verify_delivery(args.verify)
    else:
        if not args.plan or not args.output_root:
            parser.error('--plan and --output-root are required')
        exporter = export_gridded_archive if args.gridded_zip else export_anchor_year
        result = exporter(args.plan, args.output_root, dry_run=not args.execute)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
