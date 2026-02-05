#!/usr/bin/env python3
"""
pm_bridge.py - ChatGPT(PM)とClaude Code(実装担当)を自動連携するブリッジツール

プロジェクトの現状を収集し、OpenAI API経由でChatGPT(PM)に送信。
PMからの次の実装指示を取得してClaude Codeに渡せる形式で出力します。

環境変数:
    OPENAI_API_KEY: OpenAI APIキー（必須）
"""

import os
import sys
import argparse
import fnmatch
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("エラー: openaiライブラリがインストールされていません。", file=sys.stderr)
    print("以下のコマンドでインストールしてください:", file=sys.stderr)
    print("  pip install openai", file=sys.stderr)
    sys.exit(1)


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

# バイナリファイルの拡張子（読み込みスキップ対象）
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
SYSTEM_PROMPT = """あなたは優秀なプロジェクトマネージャー(PM)です。

以下の情報はClaude Code（実装担当AI）が収集したプロジェクトの現状報告です。
この情報を分析し、Claude Codeに対して次に実行すべき具体的な実装指示を出してください。

## 指示の形式
- 具体的なファイルパスを明示する
- 実装すべきコードや修正内容を明確に記述する
- 必要に応じてコマンド例を提示する
- 優先度が高いものから順に指示する

## 注意事項
- Claude Codeは指示されたことを忠実に実行します
- 曖昧な指示は避け、具体的に記述してください
- エラーがある場合は、その解決方法を具体的に指示してください
"""


def should_exclude(name: str, excludes: set) -> bool:
    """指定された名前が除外対象かどうかを判定"""
    if name in excludes:
        return True
    for pattern in excludes:
        if '*' in pattern:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def is_binary_file(filepath: str) -> bool:
    """バイナリファイルかどうかを判定"""
    ext = Path(filepath).suffix.lower()
    return ext in BINARY_EXTENSIONS


def generate_tree(root_dir: str, excludes: set = None, prefix: str = "", max_depth: int = 5, current_depth: int = 0) -> str:
    """ディレクトリのツリー構造を文字列として生成"""
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


def collect_all_files(root_dir: str, excludes: set = None, max_files: int = 50) -> list:
    """
    ディレクトリ内の全ファイルを収集

    Args:
        root_dir: 検索対象のルートディレクトリ
        excludes: 除外するパターン
        max_files: 最大ファイル数

    Returns:
        ファイルパスのリスト
    """
    if excludes is None:
        excludes = DEFAULT_EXCLUDES

    files = []

    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not should_exclude(d, excludes)]

        for filename in filenames:
            if should_exclude(filename, excludes):
                continue

            filepath = os.path.join(root, filename)

            if is_binary_file(filepath):
                continue

            files.append(filepath)

            if len(files) >= max_files:
                return files

    return files


def read_file_content(filepath: str, max_lines: int = 200) -> str:
    """ファイルの内容を読み込む"""
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
        'toml': 'toml',
        'ini': 'ini',
        'cfg': 'ini',
        'txt': 'text',
    }
    lang = lang_map.get(extension, extension or 'text')

    return f"### {rel_path}\n```{lang}\n{content}\n```"


def read_log_file(log_path: str, max_lines: int = 100) -> str:
    """ログファイルを読み込む"""
    if not os.path.exists(log_path):
        return f"[ログファイルが見つかりません: {log_path}]"

    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            content = ''.join(lines[-max_lines:])
            content = f"... (先頭 {len(lines) - max_lines} 行省略)\n" + content
        else:
            content = ''.join(lines)

        return content.rstrip()
    except Exception as e:
        return f"[ログ読み込みエラー: {e}]"


def build_context(
    root_dir: str,
    excludes: set,
    log_path: str = None,
    message: str = None,
    max_depth: int = 5,
    max_lines: int = 200,
    max_files: int = 30
) -> str:
    """
    プロジェクトのコンテキストを構築

    Returns:
        PMに送信するコンテキスト文字列
    """
    parts = []

    # プロジェクト構造
    parts.append("# プロジェクト構造")
    tree = generate_tree(root_dir, excludes, max_depth=max_depth)
    parts.append("```")
    parts.append(tree.rstrip() if tree else "(ファイルなし)")
    parts.append("```")
    parts.append("")

    # 全ファイルの内容
    parts.append("# ファイル内容")
    files = collect_all_files(root_dir, excludes, max_files=max_files)

    if files:
        for filepath in files:
            content = read_file_content(filepath, max_lines)
            formatted = format_file_content(filepath, content, root_dir)
            parts.append(formatted)
            parts.append("")
    else:
        parts.append("(対象ファイルなし)")
        parts.append("")

    # エラーログ
    if log_path:
        parts.append("# エラーログ / 実行結果")
        log_content = read_log_file(log_path)
        parts.append("```")
        parts.append(log_content)
        parts.append("```")
        parts.append("")

    # 補足メッセージ
    if message:
        parts.append("# 補足情報（実装担当からの報告）")
        parts.append(message)
        parts.append("")

    return '\n'.join(parts)


def query_pm(client: OpenAI, context: str, model: str = "gpt-4o") -> str:
    """
    OpenAI APIを使ってPM(ChatGPT)に問い合わせる

    Args:
        client: OpenAIクライアント
        context: プロジェクトのコンテキスト
        model: 使用するモデル

    Returns:
        PMからの指示
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context}
            ],
            temperature=0.7,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[APIエラー: {e}]"


def print_pm_instruction(instruction: str):
    """PMからの指示を見やすく表示"""
    border = "=" * 60
    print()
    print(border)
    print("📋 PM(ChatGPT)からの指示")
    print(border)
    print()
    print(instruction)
    print()
    print(border)
    print("💡 上記の指示をClaude Codeに渡してください")
    print(border)
    print()


def main():
    parser = argparse.ArgumentParser(
        description='ChatGPT(PM)とClaude Code(実装担当)を自動連携するブリッジツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 基本的な使用法（カレントディレクトリの情報をPMに送信）
  python pm_bridge.py

  # 特定のディレクトリを対象
  python pm_bridge.py -d /path/to/project

  # エラーログを含めて送信
  python pm_bridge.py -l error.log

  # 補足メッセージを追加
  python pm_bridge.py -m "認証機能の実装でエラーが発生しています"

  # GPT-4o-mini を使用（コスト削減）
  python pm_bridge.py --model gpt-4o-mini

  # コンテキストのみ表示（API呼び出しなし）
  python pm_bridge.py --dry-run

環境変数:
  OPENAI_API_KEY: OpenAI APIキー（必須）
        """
    )

    parser.add_argument(
        '-d', '--directory',
        default='.',
        help='対象ディレクトリ（デフォルト: カレントディレクトリ）'
    )

    parser.add_argument(
        '-l', '--log',
        help='含めるエラーログ/実行結果ファイルのパス'
    )

    parser.add_argument(
        '-m', '--message',
        help='PMへの補足メッセージ'
    )

    parser.add_argument(
        '--model',
        default='gpt-4o',
        help='使用するOpenAIモデル（デフォルト: gpt-4o）'
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
        default=200,
        help='ファイル読み込みの最大行数（デフォルト: 200）'
    )

    parser.add_argument(
        '--max-files',
        type=int,
        default=30,
        help='読み込む最大ファイル数（デフォルト: 30）'
    )

    parser.add_argument(
        '--exclude',
        action='append',
        default=[],
        help='追加で除外するパターン（複数指定可）'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='APIを呼び出さずにコンテキストのみ表示'
    )

    parser.add_argument(
        '-o', '--output',
        help='PMの指示を保存するファイルパス'
    )

    args = parser.parse_args()

    # 対象ディレクトリの検証
    root_dir = os.path.abspath(args.directory)
    if not os.path.isdir(root_dir):
        print(f"エラー: ディレクトリが見つかりません: {root_dir}", file=sys.stderr)
        sys.exit(1)

    # 除外パターンの設定
    excludes = DEFAULT_EXCLUDES.copy()
    for pattern in args.exclude:
        excludes.add(pattern)

    # コンテキストの構築
    print("📦 プロジェクト情報を収集中...", file=sys.stderr)
    context = build_context(
        root_dir=root_dir,
        excludes=excludes,
        log_path=args.log,
        message=args.message,
        max_depth=args.max_depth,
        max_lines=args.max_lines,
        max_files=args.max_files
    )

    # ドライランモード
    if args.dry_run:
        print("\n[ドライランモード - 以下のコンテキストがPMに送信されます]\n")
        print(context)
        return

    # APIキーの確認
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        print("エラー: 環境変数 OPENAI_API_KEY が設定されていません。", file=sys.stderr)
        print("以下のコマンドで設定してください:", file=sys.stderr)
        print("  export OPENAI_API_KEY='your-api-key'", file=sys.stderr)
        sys.exit(1)

    # OpenAIクライアントの初期化
    client = OpenAI(api_key=api_key)

    # PMに問い合わせ
    print(f"🤖 PM(ChatGPT)に問い合わせ中... (model: {args.model})", file=sys.stderr)
    instruction = query_pm(client, context, model=args.model)

    # 結果の出力
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(instruction)
            print(f"✅ PMの指示を保存しました: {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"ファイル保存エラー: {e}", file=sys.stderr)
            sys.exit(1)

    print_pm_instruction(instruction)


if __name__ == '__main__':
    main()
