"""SQLite 数据访问层。

选型说明（为什么不是 MySQL/PostgreSQL）：
单机单用户场景下 SQLite 零运维、零部署（整个库就是一个文件，已被 .gitignore 排除），
备份即拷贝文件；表结构是标准 SQL，将来要多用户并发时迁移到 MySQL 成本很低。
"""
