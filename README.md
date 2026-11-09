<div align="center">

# 🌟 Spotlight — ALCHE Campus Marketplace

**Discover. Connect. Trade. Grow.**

*Developed by [The Nova Group Ltd.](#-development-team)*

![React](https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-61DAFB?logo=react&logoColor=white)
![Django](https://img.shields.io/badge/Backend-Django-092E20?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Cache-Redis-DC382D?logo=redis&logoColor=white)

</div>

---

## 📌 About the Project

**Spotlight** is a hyper-local digital marketplace designed for the ALCHE campus community. It connects student entrepreneurs, service providers, and consumers through a centralized platform for buying and selling products, booking services, promoting businesses, and showcasing student ventures.

The platform aims to simplify campus commerce, empower student entrepreneurship, and create a trusted digital ecosystem for the campus community.

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 🛒 **E-Commerce Marketplace** | Multi-vendor storefronts, product listings, inventory management, shopping carts, and order tracking. |
| 📅 **Service Booking** | Appointment scheduling, provider availability, booking management, and notifications. |
| 📣 **Advertising & Promotions** | Sponsored listings, promotional banners, discount coupons, and featured products. |
| 🏆 **Business Showcase** | Student venture profiles, portfolios, project galleries, and business achievements. |
| ⭐ **Reviews & Ratings** | Customer feedback, verified reviews, and merchant reputation management. |

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Frontend | React.js, TypeScript |
| Build Tool | Vite |
| Styling | Tailwind CSS |
| Backend | Python, Django |
| API | Django REST Framework |
| Database | PostgreSQL |
| Caching | Redis |
| Version Control | Git / GitHub |

---

## 🏗️ Project Architecture

Spotlight follows a **client-server architecture** where the React frontend communicates with the Django backend through RESTful APIs.

The platform supports three primary user roles:

- **Customer** — Browse products, place orders, book services, and submit reviews.
- **Vendor** — Manage storefronts, products, inventory, bookings, and promotions.
- **Administrator** — Manage users, verify vendors, moderate content, and oversee platform operations.

---

## 📂 Project Structure

```plaintext
spotlight/
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── marketplace/
│   │   ├── products/
│   │   ├── orders/
│   │   ├── bookings/
│   │   ├── advertising/
│   │   ├── portfolios/
│   │   └── reviews/
│   ├── manage.py
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
│
├── .gitignore
└── README.md
```

> **Note:** Directory structure is illustrative and should be adapted to the actual repository.

---

## ⚙️ Installation & Setup

### Prerequisites

- Python 3.10+
- pip
- Node.js and npm
- PostgreSQL

### 1. Clone the Repository

```bash
git clone <repository-url>
cd spotlight
```

### 2. Set Up the Backend

```bash
cd backend
python -m venv venv
```

Activate the virtual environment:

```bash
# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `backend` directory:

```dotenv
SECRET_KEY=your-secret-key
DEBUG=True
DB_NAME=spotlight_db
DB_USER=postgres
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432
```

### 4. Run Database Migrations

```bash
python manage.py migrate
```

### 5. Create an Administrator

```bash
python manage.py createsuperuser
```

### 6. Start the Django Server

```bash
python manage.py runserver
```

Backend: <http://127.0.0.1:8000/>

### 7. Start the Frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend: <http://localhost:5173/>

---

## 🗺️ Development Roadmap

- [ ] **Phase 1 – Core Marketplace:** Authentication, user roles, storefronts, product management, and order processing.
- [ ] **Phase 2 – Booking & Trust:** Appointment scheduling, notifications, reviews, and ratings.
- [ ] **Phase 3 – Platform Expansion:** Advertising, business portfolios, analytics, and full campus deployment.

---

## 🔒 Security

Spotlight aims to follow Django security best practices, including:

- Secure authentication
- Role-based permissions
- Input validation
- Protected API endpoints
- Environment-based configuration

---

## 👥 Development Team

**The Nova Group Ltd.**

Project: *Spotlight — ALCHE Campus Marketplace*

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE). See the LICENSE file for details.

---

<p align="center"><strong>Spotlight — Empowering Campus Entrepreneurship Through Technology.</strong></p>
