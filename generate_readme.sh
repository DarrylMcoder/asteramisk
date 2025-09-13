#!/bin/bash
pandoc docs/intro.rst docs/installation.rst docs/configuration.rst docs/usage.rst -f rst -t markdown -o README.md
