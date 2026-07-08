# 腾讯云 MySQL 数据库接入

本项目支持可选数据库持久化。默认不启用数据库，方便每个组员本地模拟运行；配置环境变量后，会自动连接腾讯云 MySQL，并创建以下表：

- `robot_alarm`
- `robot_report`
- `robot_vision_event`
- `robot_sensor_sample`

## 启用方式

Windows PowerShell：

```powershell
$env:ICAR_DB_HOST="bj-cynosdbmysql-grp-4ra8jiia.sql.tencentcdb.com"
$env:ICAR_DB_PORT="27180"
$env:ICAR_DB_USER="root"
$env:ICAR_DB_PASSWORD="你的数据库密码"
$env:ICAR_DB_NAME="icar"
python scripts\db_check.py
```

启动后端：

```powershell
.\scripts\start_backend.ps1
```

Ubuntu / Jetson：

```bash
export ICAR_DB_HOST=bj-cynosdbmysql-grp-4ra8jiia.sql.tencentcdb.com
export ICAR_DB_PORT=27180
export ICAR_DB_USER=root
export ICAR_DB_PASSWORD='你的数据库密码'
export ICAR_DB_NAME=icar
python3 scripts/db_check.py
./scripts/start_backend.sh
```

## 注意事项

1. 数据库密码不要写进代码、README 或 GitHub。
2. 如果连接失败，先检查腾讯云安全组/白名单是否允许当前公网 IP 访问 `27180`。
3. 校内网络、手机热点、校园网认证可能影响云数据库连接。
4. 数据库只是增强项，本项目默认模拟模式不依赖数据库。

## Web 检查接口

后端启动后可以访问：

```text
http://127.0.0.1:8000/api/db/health
```
