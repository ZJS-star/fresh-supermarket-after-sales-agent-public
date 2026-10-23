"""Single-agent after-sales MVP. Trusted host modules never export arbitrary file or shell tools."""
import sys
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
DATA=PROJECT/'after_sales_dataset'
sys.path.insert(0,str(DATA))
