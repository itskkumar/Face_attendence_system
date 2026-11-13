"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Student } from "@/lib/types";
import { ErrorNote, KeyValue, PageHeader, Section } from "@/components/features/shared";
import { Skeleton } from "@/components/ui/glass";

export default function StudentProfile() {
  const q = useQuery({ queryKey: ["me-profile"], queryFn: () => api<Student>("/me/profile") });
  const s = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="My profile" />
      <ErrorNote error={q.error} />
      {q.isLoading && <Skeleton className="h-56 w-full" />}
      {s && (
        <Section title={s.name} className="max-w-xl">
          <KeyValue rows={[["Roll number", s.roll_number], ["Email", s.email || "-"], ["Phone", s.phone || "-"], ["Department", s.department || "-"], ["Batch", s.batch || "-"], ["Expected time", s.expected_time || "-"], ["Face enrolled", s.template_count > 0 ? "Yes" : "No"], ["Attendance (30 days)", s.attendance_percentage_30d !== undefined ? `${s.attendance_percentage_30d.toFixed(1)}%` : "-"]]} />
          <p className="mt-4 text-xs text-muted">To change your details or re-enroll your face, contact an administrator.</p>
        </Section>
      )}
    </div>
  );
}
