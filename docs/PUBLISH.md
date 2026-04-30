# 第一次发到 GitHub

照下面顺序复制粘贴，一次把仓库推上去。

## Step 0 — 在 GitHub 上建好账号

如果还没账号：https://github.com/signup
建议同时装一下 GitHub CLI：

```bash
# macOS
brew install gh
# Windows
winget install --id GitHub.cli
# Ubuntu / Debian
sudo apt install gh
```

跑 `gh auth login` 完成 OAuth。

## Step 1 — 本地初始化仓库

在你电脑上（不是 Pi 上），打开终端，进到 `medical-waste-sorter/` 目录：

```bash
cd medical-waste-sorter
git init
git branch -M main
git add .
git status                     # 检查没把私密文件提上去
git commit -m "Initial commit: medical waste sorting robotic arm"
```

如果 `git status` 看到 `config.yaml`、`venv/`、`models/best_ncnn_model/` 之类
的东西，说明 `.gitignore` 没生效——重检一下，然后 `git rm --cached <file>` 移掉。

## Step 2 — 在 GitHub 上建仓库并推送

用 GitHub CLI 一条命令搞定：

```bash
gh repo create medical-waste-sorter --public --source=. --remote=origin --push
```

或者手动建：
1. https://github.com/new 建一个空仓库（**不要**勾选 "Initialize with README"）
2. 然后：
   ```bash
   git remote add origin https://github.com/<你的用户名>/medical-waste-sorter.git
   git push -u origin main
   ```

## Step 3 — 如果你是从本仓库 fork 出去的，替换 owner

主仓库里所有出现 `deafenken/medical-waste-sorter` 的地方（CI 徽章、issue 模板里的链接、README 的 git clone 命令）都要换成你自己的 GitHub 路径：

```bash
# Linux / macOS  (把 YOUR_USERNAME 换成你自己的 GitHub 用户名)
find . -type f \( -name "*.md" -o -name "*.yml" \) -not -path "./.git/*" \
    -exec sed -i.bak 's|deafenken|YOUR_USERNAME|g' {} \;
find . -name "*.bak" -delete

git add -A
git commit -m "Update owner placeholders to YOUR_USERNAME"
git push
```

涉及的文件：
- `README.md`（CI 徽章）
- `.github/ISSUE_TEMPLATE/config.yml`（contact links）
- `docs/DEPLOY.md`（git clone URL）

## Step 4 — 验证 CI 跑起来

push 完去 `https://github.com/<你>/medical-waste-sorter/actions` 看，
`CI` 工作流应该自动开始跑，~2 分钟出结果。

绿了说明：
- 所有 Python 文件语法正确
- `config.example.yaml` 能被加载
- `category_to_bin` 和 `models/best.pt` 的类名对得上

红了：点开报错的 step 看具体哪一行挂了。

## Step 5 — 加点门面

仓库主页右边齿轮 ⚙️ 的位置可以设：
- **Description**：`YOLOv8 + Orbbec depth camera + G-code arm for medical waste auto-sorting on Raspberry Pi / RK3588`
- **Website**：可以留空，或填个 demo 视频链接
- **Topics**：`yolov8` `robotic-arm` `raspberry-pi` `rk3588` `medical-waste` `computer-vision`
- 勾上 Issues / Discussions（让别人能提 issue）

## Step 6 — 更新维护

之后每次本地改完代码：

```bash
git add -A
git status                     # 再检查一次
git commit -m "短描述"
git push
```

PR 流程（鼓励别人贡献时用）：

```bash
git checkout -b feature/dobot-support
# ... 改代码 ...
git commit -am "Add dobot SDK adapter"
git push -u origin feature/dobot-support
gh pr create --fill            # 自动用提交记录建 PR
```

## 常见坑

### `git push` 报 `non-fast-forward`
你或别人在远端改过东西。先拉再推：
```bash
git pull --rebase origin main
git push
```

### 不小心把 `config.yaml`（含路径/串口配置）提上去了
```bash
git rm --cached config.yaml
echo "config.yaml" >> .gitignore   # 已经在 .gitignore 里，但 double-check
git commit -m "Remove personal config"
git push
```

注意：**已经推到公开仓库的提交里，密钥还能被人在历史里翻到**。如果文件
真有敏感信息（比如 API key），用 `git filter-repo` 或 BFG 清历史，并立刻
吊销/换掉那个 secret。

### 模型 .pt 文件 push 不上去
GitHub 单文件上限 100MB。我们的 `best.pt` 只有 6MB，不会触发。
如果以后训了大模型超 100MB，看 README "模型文件" 那段，换 Git LFS 或
GitHub Release 托管。
