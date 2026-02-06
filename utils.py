#!/usr/bin/env python3
"""
utils.py - pm_bridge.pyとbridge_manager.pyの共通ユーティリティ関数

このモジュールは、プロジェクト管理ツールで使用される共通的な機能を提供します。
"""

import os
import fnmatch
from pathlib import Path

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


def should_exclude(name: str, excludes: set) -> bool:
    """
    指定された名前が除外対象かどうかを判定
    
    Args:
        name: チェックするファイル/ディレクトリ名
        excludes: 除外パターンのセット
        
    Returns:
        bool: 除外対象の場合True
    """
    if name in excludes:
        return True
    for pattern in excludes:
        if '*' in pattern:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def is_binary_file(filepath: str) -> bool:
    """
    バイナリファイルかどうかを判定
    
    Args:
        filepath: ファイルパス
        
    Returns:
        bool: バイナリファイルの場合True
    """
    ext = Path(filepath).suffix.lower()
    return ext in BINARY_EXTENSIONS


def generate_tree(root_dir: str, excludes: set = None, prefix: str = "", max_depth: int = 5, current_depth: int = 0) -> str:
    """
    ディレクトリのツリー構造を文字列として生成
    
    Args:
        root_dir: ルートディレクトリのパス
        excludes: 除外するディレクトリ/ファイル名のセット
        prefix: 出力時のプレフィックス（インデント用）
        max_depth: 最大探索深度
        current_depth: 現在の深度
        
    Returns:
        str: ツリー構造の文字列
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    if current_depth >= max_depth:
        return prefix + "...\n"

    result = []
    root_path = Path(root_dir)

    try:
        entries = sorted(root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return prefix + "[Permission Denied]\n"

    entries = [e for e in entries if not should_exclude(e.name, excludes)]

    for i, entry in enumerate(entries):
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "

        if entry.is_dir():
            result.append(f"{prefix}{connector}{entry.name}/")
            extension = "    " if is_last else "│   "
            subtree = generate_tree(
                str(entry),
                excludes,
                prefix + extension,
                max_depth,
                current_depth + 1
            )
            if subtree:
                result.append(subtree.rstrip('\n'))
        else:
            result.append(f"{prefix}{connector}{entry.name}")

    return '\n'.join(result) + '\n' if result else ""


def read_file_content(filepath: str, max_lines: int = 100) -> str:
    """
    ファイルの内容を読み込む
    
    Args:
        filepath: ファイルパス
        max_lines: 最大読み込み行数
        
    Returns:
        str: ファイル内容の文字列
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            content = ''.join(lines[:max_lines])
            content += f"\n... (以下 {len(lines) - max_lines} 行省略)"
        else:
            content = ''.join(lines)

        return content.rstrip()
    except Exception as e:
        return f"[読み込みエラー: {e}]"


def collect_files_by_pattern(root_dir: str, pattern: str, excludes: set = None) -> list:
    """
    パターンにマッチするファイルを収集
    
    Args:
        root_dir: 検索対象のルートディレクトリ
        pattern: ファイル名パターン (例: "*.py")
        excludes: 除外するパターン
        
    Returns:
        list: マッチしたファイルパスのリスト
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES
        
    files = []
    
    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not should_exclude(d, excludes)]
        
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern) and not should_exclude(filename, excludes):
                filepath = os.path.join(root, filename)
                if not is_binary_file(filepath):
                    files.append(filepath)
    
    return files


def get_recent_files(root_dir: str, num_files: int = 5, excludes: set = None) -> list:
    """
    最近更新されたファイルを取得
    
    Args:
        root_dir: 検索対象のルートディレクトリ
        num_files: 取得するファイル数
        excludes: 除外するパターン
        
    Returns:
        list: (ファイルパス, 更新日時) のタプルのリスト
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    files_with_mtime = []

    for root, dirs, files in os.walk(root_dir):
        # 除外ディレクトリをスキップ
        dirs[:] = [d for d in dirs if not should_exclude(d, excludes)]

        for filename in files:
            if should_exclude(filename, excludes):
                continue

            filepath = os.path.join(root, filename)
            if is_binary_file(filepath):
                continue
                
            try:
                mtime = os.path.getmtime(filepath)
                files_with_mtime.append((filepath, mtime))
            except (OSError, IOError):
                continue

    # 更新日時でソート（新しい順）
    files_with_mtime.sort(key=lambda x: x[1], reverse=True)

    return files_with_mtime[:num_files]