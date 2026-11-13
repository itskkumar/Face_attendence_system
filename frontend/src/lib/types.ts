export type Role = "admin" | "operator" | "student";

export interface User { username: string; role: Role; roll_number: string | null }
export interface AuthState { user: User; csrf_token: string; must_reset_password: boolean }

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface AttendanceRow {
  id: number; roll_number: string; name: string; timestamp: string; direction: string;
  similarity: number; source: string; camera_label: string; pad_state: string | null; pad_score: number | null;
}

export interface TrendPoint { date: string; unique: number; total: number }
export interface HourPoint { hour: string; count: number }
export interface PeakHour { hour: number; count: number }
export interface LateArrival { roll_number: string; name: string; timestamp: string; hour: number }

export interface Dashboard {
  today_unique: number; today_scans: number; today_known: number; today_unknown: number; enrolled_students: number;
  hourly: HourPoint[]; trends: TrendPoint[]; peak_hours: PeakHour[]; late_arrivals: LateArrival[]; recent: AttendanceRow[];
}

export interface Analytics {
  trends: TrendPoint[]; peak_hours: PeakHour[];
  camera_stats: { camera_label: string; total: number; unique_persons: number }[];
  absent: { roll_number: string; name: string }[]; late_arrivals: LateArrival[];
}

export interface Student {
  roll_number: string; name: string; email: string; phone: string; department: string; batch: string;
  expected_time: string; created_at: string; template_count: number; attendance_percentage_30d?: number;
}

export interface PadHealth {
  state: "READY" | "NOT_CONFIGURED" | "ERROR"; reason: string; model_id: string; provider?: string;
  models: { id: string; crop_scale: number }[];
}

export interface Tuning {
  similarity_threshold: number; min_blur_var: number; min_pose_score: number; detect_every_n: number;
  cooldown_seconds: number; gate_line_enabled: boolean; gate_line_orientation: string; gate_line_ratio: number;
  liveness_mode: "off" | "fft_experimental" | "minifas";
}

export interface LiveStatus {
  running: boolean; source_label: string; camera_label: string; fps: number; proc_ms: number; det_ms: number;
  rec_ms: number; pad_ms: number; faces: number; session_logged: number; provider: string; liveness_mode: string;
  pad: PadHealth; settings: Tuning; error: string | null; viewers: number;
}

export interface LiveEvent {
  event_id: string; type: string; ts: string; camera_id: string; track_id: number; status: string;
  pad_state: string | null; pad_real_prob: number | null; liveness_mode: string;
  student?: { roll_number: string; name: string }; similarity?: number; reason?: string; det_score?: number;
}

export interface Track {
  track_id: number; bbox: [number, number, number, number]; status: string; name: string | null;
  roll_number: string | null; det_score: number | null; similarity: number | null; pad_state: string | null;
  pad_real_prob: number | null; hint: string;
}

export interface PreviewFrame {
  kind: "frame"; jpeg_b64: string; width: number; height: number; tracks: Track[]; fps: number; proc_ms: number;
}

export interface Camera {
  id: string; name: string; type: "rtsp" | "webcam" | "file" | "http"; source_masked: string; description: string;
  enabled: boolean; status: "idle" | "live" | "error"; last_error: string | null;
}

export interface UserRow {
  username: string; role: Role; roll_number: string | null; must_reset: boolean; has_password: boolean;
  created_at: string; disabled: boolean;
}

export interface SystemInfo {
  cpu_percent: number; ram_percent: number; ram_used_mb: number; provider: string; fps: number; proc_ms: number;
  det_ms: number; rec_ms: number; pad_ms: number; liveness_mode: string; pad: PadHealth; worker_running: boolean;
  db_size_mb: number; alerts: { level: "info" | "warning" | "error"; message: string }[];
  history: { cpu: [number, number][]; ram: [number, number][]; fps: [number, number][] };
}

export interface PadEventRow {
  id: number; timestamp: string; camera_label: string; track_id: number; state: string; real_prob: number | null;
  spoof_prob: number | null; model_id: string; student_id: number | null; flagged: number; note: string;
}

export interface SecurityAlerts { pad_events: PadEventRow[]; unknown_today: number; spoof_today: number }

export interface Inspector {
  settings: Record<string, string | number | boolean>;
  gallery: { students: number; templates: number; version: string | number; backend: string };
  pad: PadHealth; models: { name: string; present: boolean }[];
}

export interface AuditRow { id: number; timestamp: string; user: string; action: string; details: string; ip_address: string }

export interface EnrollmentStatus { engine_ready: boolean; pad: PadHealth; liveness_mode: string; require_liveness: boolean }
export interface SampleResult {
  accepted: boolean; reason: string; pad_state: string | null; pad_real_prob: number | null; count: number; target: number;
}
