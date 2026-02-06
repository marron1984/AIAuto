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
    '.git', '.svn', '.hg', 'venv', '.venv', 'env', '.env',
    '__pycache__', 'node_modules', '.idea', '.vscode',
    '*.pyc', '*.pyo', '.DS_Store', 'Thumbs.db',
    '.pytest_cache', '.mypy_cache', '.tox',
    'dist', 'build', '*.egg-info', '*.log',
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
ファイルを作成・修正する場合は、以下の形式で出力してください:

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
            subtree = generate_tree(str(entry), excludes, prefix + extension, max_depth, current_depth + 1)
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
    return f"### {rel_path}\n```{extension}\n{content}\n```"


def collect_files_by_pattern(root_dir: str, pattern: str, excludes: set) -> list:
    """パターンにマッチするファイルを収集"""
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not should_exclude(d, excludes)]
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern) and not should_exclude(filename, excludes):
                filepath = os.path.join(root, filename)
                if not is_binary_file(filepath):
                    files.append(filepath)
    return files


def generate_project_status(root_dir: str = ".", excludes: set = None, include_all_files: bool = False, max_files: int = 20, task: str = "") -> str:
    """プロジェクトの現状をまとめたレポートを生成"""
    if excludes is None:
        excludes = DEFAULT_EXCLUDES.copy()

    report = []
    report.append("# 現在のプロジェクト状況")

    if task:
        report.append(f"# タスク: {task}")

    report.append("# プロジェクト構造")
    tree = generate_tree(root_dir, excludes)
    report.append("```")
    report.append(tree.rstrip())
    report.append("```")

    report.append("# ファイル内容")

    if include_all_files:
        files = collect_all_files(root_dir, excludes, max_files)
    else:
        important_patterns = ['*.py', '*.js', '*.ts', '*.json', '*.yaml', '*.yml', '*.md', 'requirements.txt', 'package.json']
        files = []
        for pattern in important_patterns:
            matches = collect_files_by_pattern(root_dir, pattern, excludes)
            files.extend(matches)
            if len(files) >= max_files:
                break
        files = files[:max_files]

    for filepath in files:
        content = read_file_content(filepath)
        formatted = format_file_content(filepath, content, root_dir)
        report.append(formatted)

    return '\n\n'.join(report)


def call_openai_api(project_status: str, model: str = "gpt-4o") -> str:
    """OpenAI APIを呼び出してPMからの指示を取得"""
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI library is not available.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PM_SYSTEM_PROMPT},
            {"role": "user", "content": project_status}
        ],
        temperature=0.7,
        max_tokens=4000
    )
    return response.choices[0].message.content.strip()


def call_anthropic_api(pm_instruction: str, project_context: str = "", model: str = "claude-sonnet-4-20250514") -> str:
    """Anthropic APIを呼び出してClaudeからの実装を取得"""
    if not ANTHROPIC_AVAILABLE:
        raise RuntimeError("Anthropic library is not available.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)

    user_content = pm_instruction
    if project_context:
        user_content = f"# プロジェクト状況\n{project_context}\n\n# PM指示\n{pm_instruction}"

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}]
    )
    return response.content[0].text.strip()


def extract_file_blocks(response: str) -> list:
    """Claudeの回答からファイルブロックを抽出"""
    pattern = r'```file:([^\n]+)\n(.*?)```'
    matches = re.findall(pattern, response, re.DOTALL)

    file_blocks = []
    for filepath, content in matches:
        filepath = filepath.strip()
        content = content.rstrip()
        file_blocks.append((filepath, content))
    return file_blocks


def apply_file_changes(file_blocks: list, dry_run: bool = False, interactive: bool = False) -> bool:
    """ファイル変更を適用"""
    if not file_blocks:
        print("適用するファイル変更がありません。")
        return True

    # インタラクティブモード: ユーザーに選択させる
    if interactive:
        print("\n📋 検出されたファイル変更:")
        for i, (filepath, content) in enumerate(file_blocks, 1):
            lines = len(content.split('\n'))
            print(f"  [{i}] {filepath} ({lines} 行)")

        print("\n適用するファイルを選択してください")
        print("例: 1,3 (1と3を適用) / all (全て) / none (キャンセル)")

        choice = input("選択: ").strip().lower()

        if choice == 'none':
            print("キャンセルしました。")
            return True
        elif choice == 'all':
            selected = list(range(len(file_blocks)))
        else:
            try:
                selected = [int(x.strip()) - 1 for x in choice.split(',')]
            except ValueError:
                print("無効な選択です。")
                return False

        file_blocks = [file_blocks[i] for i in selected if 0 <= i < len(file_blocks)]

    success = True
    for filepath, content in file_blocks:
        if dry_run:
            print(f"[DRY RUN] ファイル作成/更新: {filepath}")
            continue

        try:
            dir_path = os.path.dirname(filepath)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ ファイル作成/更新: {filepath}")
        except Exception as e:
            print(f"✗ ファイル書き込みエラー ({filepath}): {e}")
            success = False

    return success


def save_conversation_log(project_status: str, pm_instruction: str, claude_response: str, log_file: str = "bridge_log.txt"):
    """会話ログを保存"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"""
{'='*80}
タイムスタンプ: {timestamp}
{'='*80}

## プロジェクト状況
{project_status}

## PM指示
{pm_instruction}

## Claude実装回答
{claude_response}

"""
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        print(f"会話ログを保存しました: {log_file}")
    except Exception as e:
        print(f"ログ保存エラー: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="ChatGPT(PM)とClaude(実装担当)を自動連携するブリッジツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python pm_bridge.py --auto                    # 完全自動モード
  python pm_bridge.py --auto --confirm          # 選択モード（ファイル選択可）
  python pm_bridge.py --auto --dry-run          # ドライラン
  python pm_bridge.py --pm-only                 # PMの指示のみ取得
  python pm_bridge.py --status-only             # プロジェクト状況のみ表示
  python pm_bridge.py --auto --task "機能追加"  # タスク指定

環境変数:
  OPENAI_API_KEY     - OpenAI API キー
  ANTHROPIC_API_KEY  - Anthropic API キー
        """
    )

    parser.add_argument("--auto", action="store_true", help="完全自動モード")
    parser.add_argument("--pm-only", action="store_true", help="PMモード（指示のみ取得）")
    parser.add_argument("--implement-only", action="store_true", help="実装モード（手動入力）")
    parser.add_argument("--status-only", action="store_true", help="プロジェクト状況のみ出力")
    parser.add_argument("--confirm", action="store_true", help="ファイル適用前に確認・選択する")
    parser.add_argument("-d", "--directory", default=".", help="対象ディレクトリ")
    parser.add_argument("-t", "--task", default="", help="タスクの説明")
    parser.add_argument("--exclude", action="append", help="除外パターンを追加")
    parser.add_argument("--include-all", action="store_true", help="全ファイルを含める")
    parser.add_argument("--max-files", type=int, default=20, help="最大ファイル数")
    parser.add_argument("--dry-run", action="store_true", help="ドライランモード")
    parser.add_argument("--log-file", default="bridge_log.txt", help="ログファイル")
    parser.add_argument("--openai-model", default="gpt-4o", help="OpenAIモデル")
    parser.add_argument("--claude-model", default="claude-sonnet-4-20250514", help="Claudeモデル")

    args = parser.parse_args()

    excludes = DEFAULT_EXCLUDES.copy()
    if args.exclude:
        excludes.update(args.exclude)

    try:
        print("📊 プロジェクト状況を収集中...")
        project_status = generate_project_status(
            root_dir=args.directory,
            excludes=excludes,
            include_all_files=args.include_all,
            max_files=args.max_files,
            task=args.task
        )

        if args.status_only:
            print("\n" + project_status)
            return

        pm_instruction = ""
        claude_response = ""

        if args.auto or args.pm_only:
            print("🤖 PM (OpenAI) に指示を問い合わせ中...")
            pm_instruction = call_openai_api(project_status, args.openai_model)
            print("\n" + "="*60)
            print("📋 PM からの指示")
            print("="*60)
            print(pm_instruction)

            if args.pm_only:
                return

        if args.auto or args.implement_only:
            if args.implement_only:
                print("実装指示を入力してください（Ctrl+D で終了）:")
                pm_instruction = sys.stdin.read().strip()
                if not pm_instruction:
                    print("指示が入力されませんでした。")
                    return

            print("\n🔧 Claude に実装を依頼中...")
            claude_response = call_anthropic_api(pm_instruction, project_status, args.claude_model)
            print("\n" + "="*60)
            print("🔧 Claude からの実装回答")
            print("="*60)
            print(claude_response)

        if args.auto and claude_response:
            print("\n📝 ファイル変更を適用中...")
            file_blocks = extract_file_blocks(claude_response)

            if file_blocks:
                success = apply_file_changes(file_blocks, args.dry_run, interactive=args.confirm)
                if success and not args.dry_run:
                    print("✅ 全ての変更が正常に適用されました。")
                elif not success:
                    print("❌ 一部の変更で問題が発生しました。")
            else:
                print("ℹ️ 適用するファイル変更が見つかりませんでした。")

        if project_status and (pm_instruction or claude_response):
            save_conversation_log(project_status, pm_instruction, claude_response, args.log_file)

    except KeyboardInterrupt:
        print("\n⚠️ 中断されました。")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
