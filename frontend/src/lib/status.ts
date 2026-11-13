export const STATUS_COLORS: Record<string, string> = {
  DETECTED: "#3b82f6",
  TRACKING: "#22d3ee",
  "CHECKING LIVENESS": "#a855f7",
  "VERIFYING IDENTITY": "#eab308",
  VERIFIED: "#22c55e",
  "ATTENDANCE RECORDED": "#22c55e",
  UNKNOWN: "#f97316",
  "POSSIBLE SPOOF": "#ef4444",
  "REVIEW REQUIRED": "#9ca3af",
  "PAD NOT CONFIGURED": "#9ca3af",
};

export const statusColor = (status: string): string => STATUS_COLORS[status] ?? "#9ca3af";

export const EVENT_LABELS: Record<string, string> = {
  "face.detected": "Face detected",
  "liveness.started": "Checking liveness",
  "liveness.passed": "Liveness passed",
  "liveness.failed": "Possible spoof",
  "liveness.uncertain": "Liveness uncertain",
  "identity.verified": "Identity verified",
  "identity.unknown": "Unknown person",
  "attendance.recorded": "Attendance recorded",
  "attendance.rejected": "Attendance rejected",
  "review.required": "Review required",
  "camera.state": "Camera state",
};

export const eventColor = (type: string): string =>
  type === "attendance.recorded" || type === "liveness.passed" || type === "identity.verified" ? "#22c55e"
  : type === "liveness.failed" ? "#ef4444"
  : type === "identity.unknown" ? "#f97316"
  : type === "attendance.rejected" || type === "review.required" || type === "liveness.uncertain" ? "#9ca3af"
  : type === "liveness.started" ? "#a855f7" : "#3b82f6";
