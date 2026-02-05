#!/usr/bin/env python3
"""
bridge_manager.py - ChatGPT向け状況報告プロンプト自動生成ツール

ChatGPT（PM）とClaude（エンジニア）間のコミュニケーションを効率化するために、
プロジェクトの状況をまとめたプロンプトを自動生成します。
"""

import os
import sys
import argparse
import glob
from datetime import datetime
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
}


def should_exclude(name: str, excludes: set) -> bool:
    """指定された名前が除外対象かどうかを判定"""
    if name in excludes:
        return True
    for pattern in excludes:
        if '*' in pattern:
            import fnmatch
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


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
        ツリー構造の文字列
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

    # フィルタリング
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


def get_recent_files(root_dir: str, num_files: int = 5, excludes: set = None) -> list:
    """
    最近更新されたファイルを取得

    Args:
        root_dir: 検索対象のルートディレクトリ
        num_files: 取得するファイル数
        excludes: 除外するパターン

    Returns:
        (ファイルパス, 更新日時) のタプルのリスト
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
            try:
                mtime = os.path.getmtime(filepath)
                files_with_mtime.append((filepath, mtime))
            except (OSError, IOError):
                continue

    # 更新日時でソート（新しい順）
    files_with_mtime.sort(key=lambda x: x[1], reverse=True)

    return files_with_mtime[:num_files]


def read_file_content(filepath: str, max_lines: int = 100) -> str:
    """
    ファイルの内容を読み込む

    Args:
        filepath: ファイルパス
        max_lines: 最大読み込み行数

    Returns:
        ファイル内容の文字列
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


def format_file_content(filepath: str, content: str, root_dir: str) -> str:
    """ファイル内容をフォーマットして出力"""
    rel_path = os.path.relpath(filepath, root_dir)
    extension = Path(filepath).suffix.lstrip('.')

    # コードブロックの言語指定
    lang_map = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'jsx': 'jsx',
        'tsx': 'tsx',
        'json': 'json',
        'yaml': 'yaml',
        'yml': 'yaml',
        'md': 'markdown',
        'sh': 'bash',
        'bash': 'bash',
        'sql': 'sql',
        'html': 'html',
        'css': 'css',
        'xml': 'xml',
    }
    lang = lang_map.get(extension, extension or 'text')

    return f"## {rel_path}\n```{lang}\n{content}\n```"


def read_log_file(log_path: str, max_lines: int = 50) -> str:
    """
    ログファイルを読み込む

    Args:
        log_path: ログファイルのパス
        max_lines: 最大読み込み行数（末尾から）

    Returns:
        ログ内容の文字列
    """
    if not os.path.exists(log_path):
        return f"[ログファイルが見つかりません: {log_path}]"

    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # 末尾からmax_lines行を取得
        if len(lines) > max_lines:
            content = ''.join(lines[-max_lines:])
            content = f"... (先頭 {len(lines) - max_lines} 行省略)\n" + content
        else:
            content = ''.join(lines)

        return content.rstrip()
    except Exception as e:
        return f"[ログ読み込みエラー: {e}]"


def generate_prompt(
    tree_structure: str,
    file_contents: list,
    log_content: str = None,
    custom_message: str = None
) -> str:
    """
    ChatGPT向けのプロンプトを生成

    Args:
        tree_structure: ツリー構造の文字列
        file_contents: ファイル内容のリスト
        log_content: ログの内容
        custom_message: カスタムメッセージ

    Returns:
        完成したプロンプト
    """
    prompt_parts = []

    # ヘッダー
    prompt_parts.append("""# 役割
あなたは優秀なPMです。以下の実装報告に基づき、次に実行すべき具体的なコマンドやコード修正を指示してください。
""")

    # プロジェクト構造
    prompt_parts.append("# 現在のプロジェクト構造")
    prompt_parts.append("```")
    prompt_parts.append(tree_structure.rstrip() if tree_structure else "(ファイルなし)")
    prompt_parts.append("```")
    prompt_parts.append("")

    # ファイル内容
    prompt_parts.append("# 直近の修正ファイル内容")
    if file_contents:
        prompt_parts.extend(file_contents)
    else:
        prompt_parts.append("(対象ファイルなし)")
    prompt_parts.append("")

    # ログ
    prompt_parts.append("# 実行結果・エラーログ")
    if log_content:
        prompt_parts.append("```")
        prompt_parts.append(log_content)
        prompt_parts.append("```")
    else:
        prompt_parts.append("(ログなし)")
    prompt_parts.append("")

    # カスタムメッセージ
    if custom_message:
        prompt_parts.append("# 補足情報")
        prompt_parts.append(custom_message)
        prompt_parts.append("")

    # フッター
    prompt_parts.append("""# 依頼
上記を踏まえ、解決策または次のステップの指示をお願いします。""")

    return '\n'.join(prompt_parts)


def main():
    parser = argparse.ArgumentParser(
        description='ChatGPT向け状況報告プロンプト自動生成ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使用法（カレントディレクトリの情報を収集）
  python bridge_manager.py

  # 特定のディレクトリを対象
  python bridge_manager.py -d /path/to/project

  # 特定のファイルを含める
  python bridge_manager.py -f src/main.py -f src/utils.py

  # ログファイルを含める
  python bridge_manager.py -l error.log

  # 結果をファイルに保存
  python bridge_manager.py -o report.md

  # 最近更新されたファイル数を指定
  python bridge_manager.py -n 10

  # カスタムメッセージを追加
  python bridge_manager.py -m "認証機能の実装中にエラーが発生しました"

  # ツリーの深さを制限
  python bridge_manager.py --max-depth 3
        """
    )

    parser.add_argument(
        '-d', '--directory',
        default='.',
        help='対象ディレクトリ（デフォルト: カレントディレクトリ）'
    )

    parser.add_argument(
        '-f', '--files',
        action='append',
        default=[],
        help='含めるファイルのパス（複数指定可）'
    )

    parser.add_argument(
        '-n', '--num-files',
        type=int,
        default=5,
        help='最近更新されたファイルの取得数（デフォルト: 5）'
    )

    parser.add_argument(
        '-l', '--log',
        help='含めるログファイルのパス'
    )

    parser.add_argument(
        '-o', '--output',
        help='出力ファイルのパス（指定しない場合は標準出力）'
    )

    parser.add_argument(
        '-m', '--message',
        help='追加のカスタムメッセージ'
    )

    parser.add_argument(
        '--max-depth',
        type=int,
        default=5,
        help='ツリー構造の最大深度（デフォルト: 5）'
    )

    parser.add_argument(
        '--max-lines',
        type=int,
        default=100,
        help='ファイル読み込みの最大行数（デフォルト: 100）'
    )

    parser.add_argument(
        '--exclude',
        action='append',
        default=[],
        help='追加で除外するパターン（複数指定可）'
    )

    parser.add_argument(
        '--no-tree',
        action='store_true',
        help='ツリー構造を省略'
    )

    parser.add_argument(
        '--no-recent',
        action='store_true',
        help='最近更新されたファイルの自動取得を無効化'
    )

    args = parser.parse_args()

    # 対象ディレクトリの絶対パス
    root_dir = os.path.abspath(args.directory)

    if not os.path.isdir(root_dir):
        print(f"エラー: ディレクトリが見つかりません: {root_dir}", file=sys.stderr)
        sys.exit(1)

    # 除外パターンの設定
    excludes = DEFAULT_EXCLUDES.copy()
    for pattern in args.exclude:
        excludes.add(pattern)

    # ツリー構造の生成
    if args.no_tree:
        tree_structure = "(省略)"
    else:
        tree_structure = generate_tree(root_dir, excludes, max_depth=args.max_depth)

    # ファイル内容の収集
    file_contents = []

    # 指定されたファイル
    for filepath in args.files:
        abs_path = os.path.abspath(filepath)
        if os.path.exists(abs_path):
            content = read_file_content(abs_path, args.max_lines)
            formatted = format_file_content(abs_path, content, root_dir)
            file_contents.append(formatted)
        else:
            file_contents.append(f"## {filepath}\n[ファイルが見つかりません]")

    # 最近更新されたファイル（指定ファイルがない場合、または併用）
    if not args.no_recent and not args.files:
        recent_files = get_recent_files(root_dir, args.num_files, excludes)
        for filepath, mtime in recent_files:
            mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            content = read_file_content(filepath, args.max_lines)
            formatted = format_file_content(filepath, content, root_dir)
            formatted = f"<!-- 更新日時: {mtime_str} -->\n{formatted}"
            file_contents.append(formatted)

    # ログの読み込み
    log_content = None
    if args.log:
        log_content = read_log_file(args.log)

    # プロンプトの生成
    prompt = generate_prompt(
        tree_structure=tree_structure,
        file_contents=file_contents,
        log_content=log_content,
        custom_message=args.message
    )

    # 出力
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"レポートを保存しました: {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"ファイル保存エラー: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(prompt)


if __name__ == '__main__':
    main()
