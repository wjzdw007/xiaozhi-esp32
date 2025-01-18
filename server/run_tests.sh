#!/bin/bash

# 运行所有测试并生成覆盖率报告
pytest tests/ -v --cov=src --cov-report=term-missing "$@" 