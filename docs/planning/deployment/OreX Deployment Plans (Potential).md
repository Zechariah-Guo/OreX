## 1. What "Free Forever" Actually Means

Oracle's free tier is split into a **30-day trial** containing $300 in credits, and a core set of **Always Free** resources. Long after the 30 days expire, you retain access to these specific infrastructure pieces.

* **ARM Compute (Ampere A1)**: Up to **2 vCPUs and 12 GB of RAM**. This is an incredibly generous allocation for a free tier—it easily outclasses free tiers from AWS or Google Cloud.  
* **x86 Compute (AMD)**: Two basic Micro instances with 1 GB of RAM each.  
* **Storage**: **200 GB** of total Block Volume storage (your OS drive space) plus **10 GB** of Standard Object Storage for your user profile pictures.  
* **Network Bandwidth**: Outbound data transfers up to **10 TB per month**.

---

## 2. The Signup Strategy

Oracle is famously strict during registration to block bot farms. Follow these steps precisely to avoid instant rejection.

1. **Navigate to the Portal**: Go to the [Oracle Free Tier Sign Up](https://signup.oraclecloud.com/).
2. **Payment Verification**: You must input a valid **physical credit card or bank debit card**. Oracle will do a temporary $1 authorization charge and immediately reverse it. **Do not use a prepaid card, virtual credit card (like Privacy), or single-use card**, or the automated security screening will instantly flag and ban your name.
3. **Choose Your "Home Region" Wisely**: During setup, you select a primary geographical location (e.g., *US East - Ashburn* or *Germany - Frankfurt*). **Always Free resources can only be deployed in your Home Region, and it can never be changed after registration**. Select a region physically close to you or your target players to optimize network ping times.
4. **The "Out of Capacity" Workaround**: Free accounts frequently hit an error saying Out of host capacity when trying to spin up a free ARM server. To bypass this, immediately upgrade your account status to **Pay-As-You-Go (PAYG)** inside the console. Oracle will not charge you anything as long as you deploy free-tier resources, but it places your account into a priority queue that completely unlocks the hardware.

---

## 3. Porting Your Local App Over

Once your cloud Virtual Machine (VM) is active (ideally running a clean server OS like **Ubuntu Linux**), treat it like a brand-new computer.

### Step 1: Prep the Code Locally

Make sure your Flask game doesn't rely on local configurations.

* Move database file configurations to environmental paths.  
* Generate a requirements.txt file of your Python packages (pip freeze \> requirements.txt).  
* Push your clean project code repository to a private **GitHub** or **GitLab** account.

### Step 2: Open the Oracle Cloud Firewall Network

Oracle's network architecture is locked down by default. Even if your Flask app is running, outside web traffic cannot reach it until you configure security access lists.

1. Go to **Networking** → **Virtual Cloud Networks** in the Oracle console.  
2. Click your network's **Security List**.  
3. Add an **Ingress Rule**: Set the source to 0.0.0.0/0 (the entire internet), select the TCP protocol, and set the Destination Port to 80 (HTTP) and 443 (HTTPS).

### Step 3: Clone and Serve on the Cloud VM

Securely Shell (SSH) directly into your cloud terminal using your terminal client.

1. Install system utilities: sudo apt update && sudo apt install python3-pip python3-venv nginx.  
2. Clone your git project repository down to the server directory.  
3. Spin up an isolated Python Virtual Environment (python3 \-m venv .venv) and initialize dependencies via pip install \-r requirements.txt.  
4. Set up **Gunicorn** to run your Flask code as a continuous background daemon, and point **Nginx** to function as a reverse proxy, translating incoming web requests directly into your game loops.

### Step 4: The SQLite Database File Migration

Because SQLite relies on a single file stored directly on the hard drive, moving it is straightforward:

* **The initial launch**: If your database schema auto-generates on execution, let your migration scripts build a blank, clean system on the cloud VM.  
* **Moving old player records**: If you want to carry over local player data, install scp (Secure Copy Protocol) or use an SFTP application (like Cyberduck or FileZilla) to copy your local .db file directly onto the cloud server file system.

---

## 4. Developing New Features in the Cloud Ecosystem

Do not write code directly inside the production cloud terminal; editing live files on a remote server will eventually break your app for players. Maintain a strict decoupled lifecycle:

```mermaid
graph LR  
    subgraph Local["1. LOCAL MACHINE"]  
        A[Code features locally] --> B[Test via local Python runtime]  
    end

    subgraph Versioning["2. CODE VERSIONING"]  
        C[Commit changes] --> D[Push to GitHub repository]  
    end

    subgraph Production["3. PRODUCTION CLOUD VM"]  
        E[Run 'git pull'] --> F[Restart Gunicorn service]  
    end

    B --> C  
    D --> E  
```

### 1. Simulating the 20-Second Engine

Keep your local testing framework matching the cloud ecosystem. Run your Flask app locally on your computer with debug modes active. Once a short-selling calculation or feature works locally, push it up to your repository and download it onto your server.

### 2. Offloading Profile Pictures to Object Storage

With your app live in the cloud, you can now swap local file storage for the Oracle Object Storage bucket we discussed earlier.

* Your production Flask app running on the VM will use boto3 to stream uploaded player pictures directly into the Oracle Object bucket.  
* When your frontend requests a profile picture, it bypasses your Flask server completely and pulls the file URL straight from Oracle's global content distribution pipelines, preserving your compute CPU cycles exclusively for the high-intensity short-selling math blocks.