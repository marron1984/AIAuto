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
    OPENAI_AVAILABLE = False

# Anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
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

```file:path/to/file.py
# ファイルの完全な内容をここに記述
```

## 注意事項
- 指示されたファイルパスを正確に使用してください
- コードは完全で実行可能な状態で出力してください
- 既存ファイルの修正の場合は、ファイル全体を出力してください
- 複数ファイルがある場合は、それぞれ別のコードブロックで出力してください
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
    """ディレクトリ内の全ファイルを収集"""
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
    """プロジェクトのコンテキストを構築"""
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


def query_pm(client: "OpenAI", context: str, model: str = "gpt-4o") -> str:
    """OpenAI APIを使ってPM(ChatGPT)に問い合わせる"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PM_SYSTEM_PROMPT},
                {"role": "user", "content": context}
            ],
            temperature=0.7,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"[PM APIエラー: {e}]"


def query_claude(client: "anthropic.Anthropic", context: str, instruction: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Anthropic APIを使ってClaude(実装担当)に問い合わせる"""
    user_message = f"""# 現在のプロジェクト状況
{context}

# PMからの指示
{instruction}

上記のPMからの指示に従って、実装を行ってください。
"""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        return response.content[0].text
    except Exception as e:
        return f"[Claude APIエラー: {e}]"


def parse_file_blocks(response: str) -> list:
    """
    Claudeの応答からファイルブロックを抽出

    形式: ```file:path/to/file.py または ```python:path/to/file.py
    """
    # パターン: ```file:パス または ```言語:パス
    pattern = r'```(?:file:|(\w+):)([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, response, re.DOTALL)

    files = []
    for lang, filepath, content in matches:
        filepath = filepath.strip()
        content = content.rstrip()
        files.append({
            'path': filepath,
            'content': content,
            'language': lang or 'text'
        })

    return files


def apply_file_changes(files: list, root_dir: str, dry_run: bool = False) -> list:
    """
    抽出したファイル内容を実際に適用

    Returns:
        適用結果のリスト
    """
    results = []

    for file_info in files:
        filepath = os.path.join(root_dir, file_info['path'])
        content = file_info['content']

        if dry_run:
            results.append({
                'path': file_info['path'],
                'status': 'dry-run',
                'message': f"[ドライラン] 書き込み予定: {filepath}"
            })
            continue

        try:
            # ディレクトリがなければ作成
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            # ファイルに書き込み
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            results.append({
                'path': file_info['path'],
                'status': 'success',
                'message': f"✅ 作成/更新: {filepath}"
            })
        except Exception as e:
            results.append({
                'path': file_info['path'],
                'status': 'error',
                'message': f"❌ エラー ({filepath}): {e}"
            })

    return results


def print_section(title: str, content: str, emoji: str = "📋"):
    """セクションを見やすく表示"""
    border = "=" * 60
    print()
    print(border)
    print(f"{emoji} {title}")
    print(border)
    print()
    print(content)
    print()


def main():
    parser = argparse.ArgumentParser(
        description='ChatGPT(PM)とClaude(実装担当)を自動連携するブリッジツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # PMから指示を取得（従来モード）
  python pm_bridge.py

  # 完全自動モード（PM指示取得 → Claude実装 → ファイル適用）
  python pm_bridge.py --auto

  # 自動モード（ファイル適用前に確認）
  python pm_bridge.py --auto --confirm

  # 自動モード（ドライラン：実際には書き込まない）
  python pm_bridge.py --auto --apply-dry-run

  # Claudeに直接指示を送信（PMスキップ）
  python pm_bridge.py --direct "認証機能を実装してください"

  # エラーログを含めて送信
  python pm_bridge.py --auto -l error.log

環境変数:
  OPENAI_API_KEY: OpenAI APIキー（PMモード時に必須）
  ANTHROPIC_API_KEY: Anthropic APIキー（自動実装モード時に必須）
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
        '--pm-model',
        default='gpt-4o',
        help='PM用OpenAIモデル（デフォルト: gpt-4o）'
    )

    parser.add_argument(
        '--claude-model',
        default='claude-sonnet-4-20250514',
        help='実装用Claudeモデル（デフォルト: claude-sonnet-4-20250514）'
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
        '--auto',
        action='store_true',
        help='完全自動モード（PM → Claude → ファイル適用）'
    )

    parser.add_argument(
        '--direct',
        metavar='INSTRUCTION',
        help='PMをスキップしてClaudeに直接指示を送信'
    )

    parser.add_argument(
        '--confirm',
        action='store_true',
        help='ファイル適用前に確認を求める'
    )

    parser.add_argument(
        '--apply-dry-run',
        action='store_true',
        help='ファイル適用をドライランで実行（実際には書き込まない）'
    )

    parser.add_argument(
        '-o', '--output',
        help='結果を保存するファイルパス'
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

    # 直接指示モード（PMスキップ）
    if args.direct:
        if not ANTHROPIC_AVAILABLE:
            print("エラー: anthropicライブラリがインストールされていません。", file=sys.stderr)
            print("  pip install anthropic", file=sys.stderr)
            sys.exit(1)

        anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
        if not anthropic_key:
            print("エラー: 環境変数 ANTHROPIC_API_KEY が設定されていません。", file=sys.stderr)
            sys.exit(1)

        claude_client = anthropic.Anthropic(api_key=anthropic_key)

        print(f"🤖 Claude に問い合わせ中... (model: {args.claude_model})", file=sys.stderr)
        claude_response = query_claude(claude_client, context, args.direct, model=args.claude_model)

        print_section("Claudeからの応答", claude_response, "🔧")

        # ファイルブロックの抽出と適用
        files = parse_file_blocks(claude_response)
        if files:
            if args.confirm:
                print(f"\n📁 {len(files)} 個のファイルが検出されました:")
                for f in files:
                    print(f"   - {f['path']}")
                response = input("\nファイルを適用しますか? [y/N]: ")
                if response.lower() != 'y':
                    print("キャンセルしました。")
                    return

            results = apply_file_changes(files, root_dir, dry_run=args.apply_dry_run)
            print("\n📝 ファイル適用結果:")
            for r in results:
                print(f"   {r['message']}")

        return

    # 通常モード（PM経由）
    if not OPENAI_AVAILABLE:
        print("エラー: openaiライブラリがインストールされていません。", file=sys.stderr)
        print("  pip install openai", file=sys.stderr)
        sys.exit(1)

    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        print("エラー: 環境変数 OPENAI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    openai_client = OpenAI(api_key=openai_key)

    # PMに問い合わせ
    print(f"🤖 PM(ChatGPT)に問い合わせ中... (model: {args.pm_model})", file=sys.stderr)
    pm_instruction = query_pm(openai_client, context, model=args.pm_model)

    print_section("PM(ChatGPT)からの指示", pm_instruction, "📋")

    # 自動モードでない場合はここで終了
    if not args.auto:
        print("=" * 60)
        print("💡 --auto オプションで自動実装モードを有効にできます")
        print("=" * 60)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(pm_instruction)
            print(f"✅ PMの指示を保存しました: {args.output}", file=sys.stderr)
        return

    # 自動モード: Claudeに実装を依頼
    if not ANTHROPIC_AVAILABLE:
        print("エラー: anthropicライブラリがインストールされていません。", file=sys.stderr)
        print("  pip install anthropic", file=sys.stderr)
        sys.exit(1)

    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    if not anthropic_key:
        print("エラー: 環境変数 ANTHROPIC_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    claude_client = anthropic.Anthropic(api_key=anthropic_key)

    print(f"🔧 Claude に実装を依頼中... (model: {args.claude_model})", file=sys.stderr)
    claude_response = query_claude(claude_client, context, pm_instruction, model=args.claude_model)

    print_section("Claude(実装担当)からの応答", claude_response, "🔧")

    # ファイルブロックの抽出と適用
    files = parse_file_blocks(claude_response)
    if files:
        print(f"\n📁 {len(files)} 個のファイルが検出されました:")
        for f in files:
            print(f"   - {f['path']}")

        if args.confirm:
            response = input("\nファイルを適用しますか? [y/N]: ")
            if response.lower() != 'y':
                print("キャンセルしました。")
                return

        results = apply_file_changes(files, root_dir, dry_run=args.apply_dry_run)
        print("\n📝 ファイル適用結果:")
        for r in results:
            print(f"   {r['message']}")
    else:
        print("\n⚠️  ファイルブロックが検出されませんでした。")
        print("   Claudeの応答にファイル出力がない場合があります。")

    # 結果の保存
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(f"# PM指示\n{pm_instruction}\n\n# Claude応答\n{claude_response}")
        print(f"\n✅ 結果を保存しました: {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
