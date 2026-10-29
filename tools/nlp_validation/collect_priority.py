"""Compatibility entry point: doctrine-first collection in the unified ELT flow."""
import argparse
from elt import main as run_elt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doctrine-limit',type=int,default=50);parser.add_argument('--jurisprudence-target',type=int,default=20000)
    args=parser.parse_args();return run_elt(['--mode','all','--doctrine-limit',str(args.doctrine_limit),'--target',str(args.jurisprudence_target)])

if __name__=='__main__':raise SystemExit(main())
