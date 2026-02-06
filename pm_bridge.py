#!/usr/bin/env python3
"""
pm_bridge.py - ChatGPT(PM)とClaude(実装担当)を自動連携するブリッジツール

完全自動化フロー:
1. プロジェクトの現状を収集
2. OpenAI API (PM) に送信して指示を取得
3. Anthropic API (Claude) に指示を送信して実装を取得
4. 実装結果を自動でファイルに反映

環境変数:
    OPENAI_API_KEY: OpenAI APIキー（PMモード時に必須）
    ANTHROPIC_API_KEY: Anthropic APIキー（自動実装モード時に必須）
"""

import os
import sys
import re
import argparse
import fnmatch
from datetime import datetime
from pathlib import Path

# OpenAI
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    print("Error: openai library is not installed. Please install it using 'pip install openai'.")
    OPENAI_AVAILABLE = False

# Anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    print("Error: anthropic library is not installed. Please install it using 'pip install anthropic'.")
    ANTHROPIC_AVAILABLE = False


# 除外するディレクトリ・ファイルパターン
DEFAULT_EXCLUDES = {
    '.git',
    '.svn',
    '.hg',
    'venv',
    '.venv',
    'env',
    '.env',
    '__pycache__',
    'node_modules',
    '.idea',
    '.vscode',
    '*.pyc',
    '*.pyo',
    '.DS_Store',
    'Thumbs.db',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    'dist',
    'build',
    '*.egg-info',
    '*.log',
}

# バイナリファイルの拡張子
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.exe', '.dll', '.so', '.dylib',
    '.mp3', '.mp4', '.wav', '.avi', '.mov',
    '.ttf', '.otf', '.woff', '.woff2',
    '.pyc', '.pyo', '.class',
}

# PMへのシステムプロンプト
PM_SYSTEM_PROMPT = """あなたは優秀なプロジェクトマネージャー(PM)です。

以下の情報はClaude（実装担当AI）が収集したプロジェクトの現状報告です。
この情報を分析し、Claudeに対して次に実行すべき具体的な実装指示を出してください。

## 指示の形式
- 具体的なファイルパスを明示する
- 実装すべきコードや修正内容を明確に記述する
- 必要に応じてコマンド例を提示する
- 優先度が高いものから順に指示する

## 注意事項
- Claudeは指示されたことを忠実に実行します
- 曖昧な指示は避け、具体的に記述してください
- エラーがある場合は、その解決方法を具体的に指示してください
"""

# Claude（実装担当）へのシステムプロンプト
CLAUDE_SYSTEM_PROMPT = """あなたは優秀なソフトウェアエンジニアです。

PMからの指示に基づいて、具体的なコード実装を行ってください。

## 出力形式
ファイルを作成・修正する場合は、以下の形式で出力してください：