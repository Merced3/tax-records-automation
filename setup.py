"""Compatibility shim for the existing pip 21 editable install.

Modern pip reads pyproject.toml directly; this venv predates PEP 660.
"""
from setuptools import find_packages, setup

setup(
    name="tax-records-automation",
    version="0.2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["pdfplumber==0.11.8", "PyYAML==6.0.3"],
    python_requires=">=3.9",
    entry_points={"console_scripts": [
        "financial-automation=financial_automation.cli:main",
    ]},
)
