"""SQLite 数据库结构查看脚本。

这个脚本是一个本地调试辅助工具，用来查看 SQLite 数据库里有哪些表、
每张表有哪些字段、建表 SQL 是什么，以及前几行样例数据。

用法：
python inspect_sqlite.py data/agent.sqlite3
"""

# sqlite3 是 Python 标准库自带的 SQLite 客户端。
import sqlite3

# sys 用来读取命令行参数。
import sys

# Path 用来处理数据库文件路径。
from pathlib import Path


def quote_identifier(name: str) -> str:
    """
    安全地引用 SQLite 表名/字段名，避免表名里有空格或关键字时报错。
    """
    return '"' + name.replace('"', '""') + '"'


def truncate_value(value, max_len: int = 80):
    """
    打印样例数据时，避免特别长的文本把终端刷屏。
    """
    if value is None:
        return None

    value_str = str(value)
    if len(value_str) > max_len:
        return value_str[:max_len] + "..."
    return value_str


def inspect_sqlite_db(db_path: str, sample_rows: int = 5):
    """打印 SQLite 数据库的表结构和少量样例数据。"""

    # 把字符串路径转成 Path，便于检查文件是否存在。
    db_file = Path(db_path)

    # 文件不存在时直接提示，不尝试创建数据库。
    if not db_file.exists():
        print(f"数据库文件不存在: {db_file}")
        return

    print("=" * 80)
    print(f"正在查看数据库: {db_file.resolve()}")
    print("=" * 80)

    try:
        # 连接数据库。这里只读元信息和样例数据，不修改数据库。
        conn = sqlite3.connect(str(db_file))

        # row_factory 让查询结果可以用 row["字段名"] 访问。
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. 查看所有表
        cursor.execute("""
            SELECT name, type
            FROM sqlite_master
            WHERE type IN ('table', 'view')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name;
        """)

        objects = cursor.fetchall()

        if not objects:
            print("没有找到用户自定义表或视图。")
            return

        print("\n数据库中的表/视图：")
        for obj in objects:
            print(f"  - {obj['name']} ({obj['type']})")

        # 2. 查看每张表的字段信息
        for obj in objects:
            table_name = obj["name"]
            object_type = obj["type"]

            print("\n" + "=" * 80)
            print(f"{object_type.upper()}: {table_name}")
            print("=" * 80)

            # PRAGMA table_xinfo 比 table_info 更完整，可以看到隐藏列/生成列
            cursor.execute(f"PRAGMA table_xinfo({quote_identifier(table_name)});")
            columns = cursor.fetchall()

            print("\n字段信息：")
            if not columns:
                print("  无字段信息。")
            else:
                print(f"{'序号':<6} {'字段名':<25} {'类型':<15} {'非空':<8} {'默认值':<20} {'主键':<8} {'隐藏列':<8}")
                print("-" * 100)

                for col in columns:
                    print(
                        f"{col['cid']:<6} "
                        f"{col['name']:<25} "
                        f"{str(col['type']):<15} "
                        f"{col['notnull']:<8} "
                        f"{str(col['dflt_value']):<20} "
                        f"{col['pk']:<8} "
                        f"{col['hidden']:<8}"
                    )

            # 3. 查看建表 SQL
            cursor.execute("""
                SELECT sql
                FROM sqlite_master
                WHERE name = ?;
            """, (table_name,))
            sql_row = cursor.fetchone()

            print("\n建表/建视图 SQL：")
            if sql_row and sql_row["sql"]:
                print(sql_row["sql"])
            else:
                print("  无 SQL 信息。")

            # 4. 统计行数
            if object_type == "table":
                try:
                    # 表名不能作为 SQL 参数绑定，所以使用 quote_identifier 安全引用。
                    cursor.execute(f"SELECT COUNT(*) AS cnt FROM {quote_identifier(table_name)};")
                    count = cursor.fetchone()["cnt"]
                    print(f"\n总行数: {count}")
                except sqlite3.Error as e:
                    print(f"\n统计行数失败: {e}")

            # 5. 查看前几行数据
            print(f"\n前 {sample_rows} 行数据：")
            try:
                # LIMIT 的值可以作为参数绑定，避免拼接数字。
                cursor.execute(
                    f"SELECT * FROM {quote_identifier(table_name)} LIMIT ?;",
                    (sample_rows,)
                )
                rows = cursor.fetchall()

                if not rows:
                    print("  表中暂无数据。")
                else:
                    # rows[0].keys() 读取字段名，作为样例表头。
                    col_names = rows[0].keys()

                    print(" | ".join(col_names))
                    print("-" * 100)

                    for row in rows:
                        # truncate_value 避免长 Markdown / JSON 内容把终端刷屏。
                        values = [str(truncate_value(row[col])) for col in col_names]
                        print(" | ".join(values))

            except sqlite3.Error as e:
                print(f"  读取样例数据失败: {e}")

        conn.close()

    except sqlite3.Error as e:
        print("SQLite 打开或读取失败：")
        print(e)


if __name__ == "__main__":
    # 直接运行脚本时，从命令行读取数据库路径。
    if len(sys.argv) < 2:
        print("用法：")
        print("python inspect_sqlite.py your_database.db")
        print()
        print("示例：")
        print("python inspect_sqlite.py app.db")
    else:
        db_path = sys.argv[1]
        inspect_sqlite_db(db_path, sample_rows=5)


'''
在vscode中怎么运行：
1. 打开终端（Terminal）。
2. 输入以下命令，替换路径为你的SQLite数据库文件路径：
   ```
   python inspect_sqlite.py your_database.db
   ```
'''
