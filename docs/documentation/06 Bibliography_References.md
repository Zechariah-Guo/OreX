# Bibliography and References — OreX

## 1. Document Purpose

This document lists all external resources, libraries, documentation, and learning materials consulted or used during the development of OreX. References are organised by category.

---

## 2. Software Libraries and Frameworks

### 2.1 Backend (Python)

| Library | Version | Purpose | URL |
|---------|---------|---------|-----|
| Python | 3.9+ | Programming language | https://www.python.org/ |
| Flask | 3.1.3 | Web application framework | https://flask.palletsprojects.com/ |
| Flask-Login | 0.6.3 | User session and authentication management | https://flask-login.readthedocs.io/ |
| Flask-WTF | 1.3.0 | CSRF protection and form handling | https://flask-wtf.readthedocs.io/ |
| Werkzeug | 3.1.8 | HTTP utilities and password hashing (PBKDF2) | https://werkzeug.palletsprojects.com/ |
| Jinja2 | 3.1.6 | HTML templating engine | https://jinja.palletsprojects.com/ |
| WTForms | 3.2.2 | Form rendering and validation (used via Flask-WTF) | https://wtforms.readthedocs.io/ |
| SQLite3 | Built-in | Relational database engine | https://www.sqlite.org/ |

### 2.2 Frontend (Client-Side)

| Library | Version | Purpose | URL |
|---------|---------|---------|-----|
| HTMX | 1.9.12 | Partial page updates and polling without a JavaScript framework | https://htmx.org/ |

---

## 3. Official Documentation

| Resource | URL | How It Was Used |
|----------|-----|-----------------|
| Flask Documentation | https://flask.palletsprojects.com/en/3.0.x/ | Application factory pattern, blueprints, configuration, error handlers, template rendering |
| Flask-Login Documentation | https://flask-login.readthedocs.io/en/latest/ | User loader, login_required decorator, session management, login_view configuration |
| Flask-WTF Documentation | https://flask-wtf.readthedocs.io/en/1.2.x/ | Global CSRF protection setup via CSRFProtect, token injection in templates |
| Werkzeug Security Documentation | https://werkzeug.palletsprojects.com/en/3.0.x/utils/#module-werkzeug.security | generate_password_hash and check_password_hash usage for secure password storage |
| Jinja2 Template Designer Documentation | https://jinja.palletsprojects.com/en/3.1.x/templates/ | Template inheritance, blocks, includes, filters, auto-escaping |
| HTMX Documentation | https://htmx.org/docs/ | hx-get, hx-trigger, hx-swap attributes; HX-Request header detection for partial responses |
| SQLite Documentation | https://www.sqlite.org/docs.html | CREATE TABLE syntax, indexes, WAL journal mode, foreign key pragmas |
| Python threading Module | https://docs.python.org/3/library/threading.html | Thread class, daemon threads, Lock for thread-safe shared state |
| Python sqlite3 Module | https://docs.python.org/3/library/sqlite3.html | Connection management, Row factory, parameterised queries, executescript |
| Python random Module | https://docs.python.org/3/library/random.html | random.choices for weighted random selection, random.uniform for range-based values |

---

## 4. Security References

| Resource | URL | How It Was Used |
|----------|-----|-----------------|
| OWASP Top 10 Web Application Security Risks | https://owasp.org/www-project-top-ten/ | Guided security decisions: SQL injection prevention (parameterised queries), broken authentication (hashing, rate limiting), CSRF protection |
| OWASP Password Storage Cheat Sheet | https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html | Confirmed PBKDF2 as an acceptable hashing algorithm; informed decision not to store plaintext |
| OWASP Session Management Cheat Sheet | https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html | Informed secure cookie configuration and session timeout considerations |
| OWASP Cross-Site Request Forgery Prevention | https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html | Justified synchroniser token pattern implemented via Flask-WTF |

---

## 5. Design and Architecture References

| Resource | URL | How It Was Used |
|----------|-----|-----------------|
| Flask Application Factory Pattern | https://flask.palletsprojects.com/en/3.0.x/patterns/appfactories/ | Informed the create_app() structure used in app/__init__.py |
| Flask Blueprints Documentation | https://flask.palletsprojects.com/en/3.0.x/blueprints/ | Guided the modular route separation into 9 feature-based blueprints |
| SQLite Write-Ahead Logging | https://www.sqlite.org/wal.html | Justified the use of WAL mode for concurrent read/write access from multiple threads |
| Python Daemon Threads | https://docs.python.org/3/library/threading.html#thread-objects | Informed the decision to run the market engine as a daemon thread that exits with the main process |

---

## 6. Algorithm and Simulation References

| Resource | URL | How It Was Used |
|----------|-----|-----------------|
| Random Walk Theory (Investopedia) | https://www.investopedia.com/terms/r/randomwalktheory.asp | Informed the probabilistic price movement model (rise/hold/fall weighted random) |
| Mean Reversion (Investopedia) | https://www.investopedia.com/terms/m/meanreversion.asp | Informed the gravity effect that pulls prices back toward their base price |
| Market Volatility (Investopedia) | https://www.investopedia.com/terms/v/volatility.asp | Informed the volatility scaling and disruption mechanics that differentiate ore risk profiles |
| Supply and Demand (Economics) | https://www.investopedia.com/terms/l/law-of-supply-demand.asp | Informed the player/bot influence system where buy pressure raises prices and sell pressure lowers them |

---

## 7. Minecraft Theme References

| Resource | URL | How It Was Used |
|----------|-----|-----------------|
| Minecraft Wiki — Ore | https://minecraft.wiki/w/Ore | Reference for ore names, rarity tiers, and the intuitive value hierarchy (coal < iron < gold < diamond < netherite) |
| Minecraft Wiki — Trading | https://minecraft.wiki/w/Trading | Inspiration for the emerald as a currency-themed ore with moderate volatility |

---

## 8. Development Tools

| Tool | Purpose | URL |
|------|---------|-----|
| Visual Studio Code | Code editor and integrated terminal | https://code.visualstudio.com/ |
| Git | Version control | https://git-scm.com/ |
| GitHub Classroom | Repository hosting and submission | https://classroom.github.com/ |
| Python venv | Virtual environment for dependency isolation | https://docs.python.org/3/library/venv.html |
| pip | Python package installer | https://pip.pypa.io/ |
| SQLite Browser (DB Browser for SQLite) | Database inspection during development | https://sqlitebrowser.org/ |
| Chrome DevTools | Frontend debugging, network monitoring, responsive testing | https://developer.chrome.com/docs/devtools/ |

---

## 9. Learning Resources

| Resource | Type | URL | Topic |
|----------|------|-----|-------|
| Flask Mega-Tutorial (Miguel Grinberg) | Tutorial Series | https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-i-hello-world | Flask application structure, user authentication, database integration |
| Real Python — Flask by Example | Tutorial | https://realpython.com/flask-by-example-part-1-project-setup/ | Flask project setup and configuration patterns |
| HTMX Essays — Hypermedia Systems | Documentation | https://htmx.org/essays/ | Philosophy of hypermedia-driven applications and when to use HTMX over SPAs |
| SQLite Tutorial | Tutorial | https://www.sqlitetutorial.net/ | SQL syntax, indexing, and query optimisation for SQLite |

---

## 10. Image Assets

| Asset | Source | Licence | Usage |
|-------|--------|---------|-------|
| Ore icons (Coal, Iron, Copper, Gold, Lapis Lazuli, Redstone, Emerald, Diamond, Netherite) | Minecraft Wiki | Fair use for educational purposes | Ore card icons on market overview and detail pages |
| OreX Logo | Original creation | N/A (project-specific) | Site branding in navigation and landing page |

---

## 11. Standards and Specifications

| Standard | URL | Relevance |
|----------|-----|-----------|
| HTML Living Standard (WHATWG) | https://html.spec.whatwg.org/ | Semantic HTML structure, form elements, accessibility attributes |
| CSS Specifications (W3C) | https://www.w3.org/Style/CSS/ | Custom properties, flexbox, grid layout, responsive design |
| WCAG 2.1 (Web Content Accessibility Guidelines) | https://www.w3.org/TR/WCAG21/ | Colour contrast, keyboard navigation, form labels, skip links |
| RFC 6238 — TOTP Algorithm | https://datatracker.ietf.org/doc/html/rfc6238 | Referenced during design of the planned (not implemented) two-factor authentication feature |
| HTTP/1.1 Specification (RFC 9110) | https://datatracker.ietf.org/doc/html/rfc9110 | HTTP methods, status codes, and header semantics used throughout the application |

