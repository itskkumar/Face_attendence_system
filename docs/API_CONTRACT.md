# API contract (FastAPI backend <-> Next.js frontend)

Base: `/api` (Next.js rewrites `/api/*` and `/ws/*` to the backend, so the browser is same-origin).
Auth: HTTP-only cookie `fa_session` (SameSite=Lax). Every non-GET request must send header
`X-CSRF-Token: <csrf_token>` (returned by `/api/auth/login` and `/api/auth/me`). Errors: JSON
`{"detail": "message"}` with 400/401/403/404/409/422/429/503. 401 = not logged in, 403 = wrong role.
Roles: `admin`, `operator`, `student`. Lists use `?page=1&page_size=25` and return
`{items: [...], total: n, page: n, page_size: n}`. Timestamps are `YYYY-MM-DD HH:MM:SS` local strings.
Embeddings/templates and RTSP credentials never appear in any response.

## Auth
- `GET /auth/status` -> `{setup_required: bool}` (public)
- `POST /auth/setup` `{setup_token, username, password}` -> `{user, csrf_token}` (public, only while no admin has a password; the token is printed in the API server log)
- `POST /auth/login` `{username, password}` -> `{user: {username, role, roll_number|null}, csrf_token, must_reset_password}` (429 when rate limited)
- `POST /auth/logout` -> `{ok: true}`
- `GET /auth/me` -> `{user, csrf_token, must_reset_password}`
- `POST /auth/change-password` `{current_password, new_password}` -> `{ok: true}` (min 10 chars)

## Dashboard (admin, operator)
`GET /dashboard` -> `{today_unique, today_scans, today_known, today_unknown, enrolled_students, hourly: [{hour: "09", count}], trends: [{date, unique, total}], peak_hours: [{hour: 9, count}], late_arrivals: [{roll_number, name, timestamp, hour}], recent: [AttendanceRow]}`

## Attendance / Search (admin, operator)
`AttendanceRow = {id, roll_number, name, timestamp, direction, similarity, source, camera_label, pad_state|null, pad_score|null}`
- `GET /attendance?page&page_size&start_date&end_date&roll_number&name&camera_label&direction` -> Page<AttendanceRow>
- `GET /attendance/export.csv?<same filters>` -> text/csv
- `GET /attendance/cameras` -> `string[]` (distinct camera labels)

## Analytics (admin, operator)
- `GET /analytics?days=30` -> `{trends: [{date, unique, total}], peak_hours: [{hour, count}], camera_stats: [{camera_label, total, unique_persons}], absent: [{roll_number, name}], late_arrivals: [...]}`

## Students (admin; operator read-only)
`Student = {roll_number, name, email, phone, department, batch, expected_time, created_at, template_count}`
- `GET /students?page&page_size&q` -> Page<Student>
- `GET /students/{roll}` -> Student & `{attendance_percentage_30d}`
- `POST /students/{roll}/profile` (admin) `{name, email, phone, department, batch, expected_time}` -> Student  (edit details; use PUT-like semantics)
- `DELETE /students/{roll}` (admin) -> `{ok}` (audit logged)
- `POST /students/import` (admin, multipart `file`=CSV with columns roll_number,name[,email,phone,department,batch,expected_time]) -> `{updated, skipped, errors: string[]}` (metadata update for EXISTING students only; the existing `Store.bulk_import_students` cannot create a student without a face template, so unknown roll numbers are reported in `errors`)

## Enrollment (admin)
- `GET /enrollment/status` -> `{engine_ready, pad: PadHealth, liveness_mode, require_liveness: bool}`
- `POST /enrollment/session` `{roll_number, name, email?, phone?, department?, batch?, expected_time?, mode: "replace"|"append"}` -> `{session_id, target_samples: 5}`
- `POST /enrollment/session/{id}/sample` multipart `image` (JPEG from the browser camera) -> `{accepted: bool, reason: string, pad_state: string|null, pad_real_prob: number|null, count: number, target: number}`
  (when PAD is READY the sample must be LIVE; SPOOF samples are always rejected; when PAD is not configured samples are accepted and the session is recorded as "liveness not verified" unless the server sets ENROLL_REQUIRE_LIVENESS=1, in which case `require_liveness` is true and the sample endpoint returns 503)
- `POST /enrollment/session/{id}/finish` -> `{ok, templates, liveness_verified: bool}`
- `DELETE /enrollment/session/{id}` -> `{ok}`
- `POST /enrollment/photos` multipart `roll_number, name, files[] (1-8 images), mode` -> `{ok, templates, rejected: [{filename, reason}], liveness_verified: false}` (audit logged "liveness not verified")

## Users (admin)
`UserRow = {username, role, roll_number|null, must_reset, has_password, created_at, disabled}`
- `GET /users` -> UserRow[]
- `POST /users` `{username, role, roll_number?, password}` -> UserRow
- `PATCH /users/{username}` `{role?, disabled?, roll_number?}` -> UserRow
- `POST /users/{username}/temporary-password` -> `{temporary_password}` (shown once; user must change it at next login)
- `DELETE /users/{username}`
- `POST /users/student-accounts` `{roll_numbers: string[]}` -> `{created: [{username, temporary_password}]}`

## Cameras (admin; operator read)
`Camera = {id, name, type: "rtsp"|"webcam"|"file"|"http", source_masked, description, enabled, status: "idle"|"live"|"error", last_error|null}`
- `GET /cameras` -> Camera[]; `POST /cameras` `{name, type, source, description, enabled}`; `PUT /cameras/{id}` same body (omit `source` to keep it); `DELETE /cameras/{id}`

## Live gate worker (admin start/stop/tune; operator view)
`Status = {running, source_label, camera_label, fps, proc_ms, det_ms, rec_ms, pad_ms, faces, session_logged, provider, liveness_mode, pad: PadHealth, settings: Tuning, error|null, viewers}`
`Tuning = {similarity_threshold, min_blur_var, min_pose_score, detect_every_n, cooldown_seconds, gate_line_enabled, gate_line_orientation, gate_line_ratio, liveness_mode}`
`PadHealth = {state: "READY"|"NOT_CONFIGURED"|"ERROR", reason, model_id, provider, models: []}`
- `GET /live/status` -> Status
- `POST /live/start` `{source: "server_webcam"|"camera"|"file"|"browser", camera_id?, webcam_index?, file_path?, loop?, camera_label?, settings?: Partial<Tuning>}` -> Status
- `POST /live/upload-video` (multipart `file`) -> `{file_path}` (server-side path to use in start)
- `POST /live/stop` -> Status; `PUT /live/settings` Partial<Tuning> -> Status (applied via dataclasses.replace; restarts the pipeline)
- `GET /live/events?limit=50` -> `LiveEvent[]` (recent)
- `LiveEvent = {event_id, type, ts, camera_id, track_id, status, pad_state|null, pad_real_prob|null, liveness_mode, student?: {roll_number, name}, similarity?, reason?, det_score?}`
  types: face.detected, liveness.started, liveness.passed, liveness.failed, liveness.uncertain, identity.verified, identity.unknown, attendance.recorded, attendance.rejected, review.required, camera.state

## WebSockets (cookie auth + Origin check; no tokens in URLs). Paths: `/ws/events`, `/ws/preview`, `/ws/browser-camera`
- `/ws/events` (admin, operator): server pushes JSON `{kind: "event", event: LiveEvent}` and `{kind: "status", status: Status}` every ~1 s.
- `/ws/preview` (admin, operator): server pushes JSON text `{kind: "frame", jpeg_b64, width, height, tracks: Track[], fps, proc_ms}` at <= 12 fps, ONLY while connected (the worker draws nothing extra for you; `tracks` lets the UI animate labels). `Track = {track_id, bbox: [x1,y1,x2,y2] in preview pixel coords, status, name|null, roll_number|null, det_score|null, similarity|null, pad_state|null, pad_real_prob|null, hint}`. status is one of: DETECTED, TRACKING, CHECKING LIVENESS, VERIFYING IDENTITY, VERIFIED, ATTENDANCE RECORDED, UNKNOWN, POSSIBLE SPOOF, REVIEW REQUIRED, PAD NOT CONFIGURED.
- `/ws/browser-camera` (admin, operator): client sends binary JPEG frames (<= ~10 fps, width <= 960); server replies `{kind: "ack", dropped: n}` JSON occasionally. Requires an active `source: "browser"` live session.
- Close codes: 4401 unauthenticated, 4403 forbidden/bad origin, 4409 no active browser session.

## System / Inspector / Security
- `GET /system` (admin, operator) -> `{cpu_percent, ram_percent, ram_used_mb, provider, fps, proc_ms, det_ms, rec_ms, pad_ms, liveness_mode, pad: PadHealth, worker_running, db_size_mb, alerts: [{level: "info"|"warning"|"error", message}], history: {cpu: [[ts, v]], ram: [[ts, v]], fps: [[ts, v]]}}` (no GPU/ANE numbers are reported)
- `GET /inspector` (admin) -> `{settings: Tuning & {...all Settings fields}, gallery: {students, templates, version, backend}, pad: PadHealth, models: [{name, present}]}` (read-only, no embeddings)
- `GET /security/alerts?limit=50` (admin, operator) -> `{pad_events: [{id, timestamp, camera_label, track_id, state, real_prob, spoof_prob, model_id, student_id, flagged, note}], unknown_today: n, spoof_today: n}`
- `GET /audit?page&page_size` (admin) -> Page<{id, timestamp, user, action, details, ip_address}>

## Student self-service (role student; data scoped to the logged-in user's roll_number)
- `GET /me/profile` -> Student & `{attendance_percentage_30d}`
- `GET /me/attendance?page&page_size&start_date&end_date` -> Page<AttendanceRow>
- `GET /me/summary` -> `{today: AttendanceRow[], week_count, month_count, attendance_percentage_30d, trends: [{date, count}]}`
