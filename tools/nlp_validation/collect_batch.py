"""Compatibility entry point: one raw collection and offline processing cycle."""
import argparse
from elt import main as run_elt

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--limit',type=int,default=1000)
    args=parser.parse_args();return run_elt(['--mode','all','--once','--batch-size',str(args.limit)])

if __name__=='__main__':raise SystemExit(main())
