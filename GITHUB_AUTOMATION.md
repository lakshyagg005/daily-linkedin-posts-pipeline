# GitHub Cloud Automation Guide — Personal Brand Daily Content Pipeline

This repository is configured for automated daily execution via **GitHub Actions** on a free `ubuntu-latest` runner. The pipeline generates content every morning automatically, even when your local machine is powered off or offline.

---

## 1. What Was Added

- **Workflow File**: `.github/workflows/daily-personal-brand.yml`
  - Automated daily schedule at **08:17 Asia/Kolkata (IST)** (`02:47 UTC`).
  - `workflow_dispatch` trigger for manual on-demand runs with optional `--force` parameter.
  - Concurrency group `personal-brand-daily` to prevent duplicate parallel runs.
  - Strict quality validation step checking manifest, 1 LinkedIn post, 3 X posts, 7 PNG slides, 1 PDF, and the **Lakshya Goyal** watermark.
  - Artifact upload step storing generated daily assets with a **7-day retention period**.
- **Dependencies**:
  - `requirements.txt`: Python dependency specification (`Pillow>=10.0.0`).
  - `carousel-routine/package.json`: Node.js dependency specification for Puppeteer rendering.
- **Security & Secret Safeguards**:
  - Updated `.gitignore` to guarantee `.env`, secrets, credentials, and output directories are never committed.
  - Enforced `LLM_FREE_ONLY=true` in environment configuration.

---

## 2. GitHub Secrets Setup (Required Once)

To allow the cloud runner to call free LLM providers without committing keys to git:

1. Go to your GitHub Repository: `https://github.com/lakshyagg005/daily-linkedin-posts-pipeline` (or your repository URL).
2. Click **Settings** → **Secrets and variables** → **Actions**.
3. Click **New repository secret**.
4. Add the following free API keys as Repository Secrets:
   - **`OPENROUTER_API_KEY`**: Your OpenRouter API Key.
   - **`GROQ_API_KEY`**: Your Groq API Key.
   - **`GEMINI_API_KEY`**: Your Gemini API Key.
5. Click **Add secret** for each.

> ⚠️ **SECURITY WARNING**: NEVER commit raw API keys to git or write actual secret values in code or documentation files.

---

## 3. How to Enable & Trigger Workflow

### Enabling Actions
1. Navigate to the **Actions** tab in your GitHub repository.
2. If prompted, click **"I understand my workflows, go ahead and enable them"**.

### Scheduled Execution
- **Daily Schedule**: Runs automatically once per day at **08:17 AM Asia/Kolkata (IST)** (`02:47 UTC`).

### Manual Trigger (On-Demand Execution)
1. Go to the **Actions** tab on GitHub.
2. Select **Personal Brand Daily Content Pipeline** from the left sidebar workflows list.
3. Click **Run workflow** dropdown on the right side.
4. Select the `main` branch.
5. (Optional) Check **"Force overwrite existing daily output"** if re-running for a date that already has generated output.
6. Click the green **Run workflow** button.

---

## 4. Downloading Artifacts & Viewing Outputs

After a successful workflow run:

1. Open the run summary under **Actions** → **Personal Brand Daily Content Pipeline** → Select latest run.
2. Scroll down to the **Artifacts** section at the bottom.
3. Click on `daily-personal-brand-content-YYYY-MM-DD.zip` to download.

### Artifact Zip Contents:
- `content/linkedin/YYYY-MM-DD/linkedin_post.md` (LinkedIn caption + source link)
- `content/x/YYYY-MM-DD/x_posts.md` & `x_posts.json` (3 distinct X posts: Interesting, Contrarian, Builder)
- `content/YYYY-MM-DD/daily_manifest.json` & `daily_content_package.json`
- `carousel-routine/output/YYYY-MM-DD/personal-brand/slide-01.png` ... `slide-07.png` (7 PNG slides with **Lakshya Goyal** watermark)
- `carousel-routine/output/YYYY-MM-DD/personal-brand/carousel-YYYYMMDD.pdf` (Combined 7-page PDF)

---

## 5. Disabling or Pausing the Workflow

If you want to temporarily stop daily automatic runs:

1. Go to the **Actions** tab in your GitHub repository.
2. Select **Personal Brand Daily Content Pipeline** from the sidebar.
3. Click the **`...`** (three dots) icon at the top right of the workflow view.
4. Click **Disable workflow**.
5. To re-enable later, click **Enable workflow**.

---

## 6. Keeping the Project ₹0/Month (Cost Control)

This automation is strictly designed for **₹0/month** total cost:

- **Runner**: Uses standard `ubuntu-latest` Linux runners included in GitHub Free tier (2,000 free Actions minutes/month; 1 daily run takes ~1-2 min = ~45-60 min/month).
- **No Paid Models**: `LLM_FREE_ONLY=true` prevents accidental paid API consumption.
- **No macOS/Windows Runners**: Uses Linux runner to conserve build minutes.
- **Storage Retention**: Artifacts auto-expire in 7 days to stay well within free storage limits.
- **No Browser Publishing Automation**: Keeps account safe and avoids headless browser login traps.

---

## 7. Troubleshooting Workflow Failures

- **Missing Secret Error**: If logs show `No free LLM provider credentials found`, verify secrets are set in Repository Settings → Secrets → Actions.
- **Duplicate Output Block**: If a run fails with `Daily output already exists`, use **Run workflow** with `force: true`.
- **Validation Failure**: The workflow automatically validates that 1 LinkedIn post, 3 X posts, 7 PNG slides, 1 PDF, and watermarks exist. Check step logs under `Validate Output Quality & Artifact Integrity` if validation fails.
