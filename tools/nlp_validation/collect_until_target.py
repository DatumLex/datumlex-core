"""Compatibility entry point for the unified local ELT workflow."""
import argparse
from elt import main as run_elt

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',type=int,default=20000)
    args=parser.parse_args();return run_elt(['--mode','all','--target',str(args.target)])

if __name__=='__main__':raise SystemExit(main())
