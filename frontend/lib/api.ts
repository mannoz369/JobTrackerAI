export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type GmailWatchState = {
  status: "not_registered" | "registered" | "expired";
  history_id: string | null;
  expiration: string | null;
  topic_name: string | null;
  last_registered_at: string | null;
};

export type AuthStatus = {
  authenticated: boolean;
  connected: boolean;
  email: string | null;
  monitored_email: string | null;
  gmail_watch: GmailWatchState | null;
};

export type ApplicationStatus =
  | "Applied"
  | "Reviewing"
  | "Assessment"
  | "Interview"
  | "Offer"
  | "Rejected"
  | "Other";

export const primaryStatuses: ApplicationStatus[] = [
  "Applied",
  "Reviewing",
  "Assessment",
  "Interview",
  "Rejected",
  "Offer",
];

export type ExtractionEvidence = {
  field: string;
  snippet: string;
};

export type JobEmailExtraction = {
  isJobRelated: boolean;
  company: string | null;
  role: string | null;
  jobId: string | null;
  location: string | null;
  emailType: string;
  statusSignal: ApplicationStatus;
  dates: Array<{
    label: string;
    text: string;
    isoDate: string | null;
  }>;
  senderDomain: string | null;
  confidence: number;
  evidence: ExtractionEvidence[];
  ambiguousIndicators: string[];
  uniqueKeywords: string[];
  reviewReason: string | null;
};

export type ApplicationSummary = {
  id: string;
  company_id: string | null;
  company_name: string;
  role: string;
  job_id: string | null;
  location: string | null;
  current_status: ApplicationStatus;
  source_email_id: string | null;
  confidence: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type StatusCount = {
  status: ApplicationStatus;
  count: number;
};

export type ApplicationsOverview = {
  total: number;
  review_queue_count: number;
  status_counts: StatusCount[];
  recent_applications: ApplicationSummary[];
};

export type CompanyApplicationGroup = {
  company_id: string | null;
  company_name: string;
  application_count: number;
  status_counts: StatusCount[];
  applications: ApplicationSummary[];
};

export type StatusUpdate = {
  id: string;
  email_id: string | null;
  previous_status: ApplicationStatus | null;
  new_status: ApplicationStatus;
  source: "email" | "manual" | "system";
  confidence: number | null;
  explanation: string | null;
  match_method: string | null;
  evidence: ExtractionEvidence[];
  created_at: string;
};

export type ApplicationDetail = {
  application: ApplicationSummary;
  timeline: StatusUpdate[];
};

export type DeleteApplicationResponse = {
  id: string;
  deleted: boolean;
  deleted_status_updates: number;
  relinked_review_emails: number;
};

export type ReviewQueueItem = {
  email_id: string;
  sender: string | null;
  subject: string | null;
  received_at: string | null;
  snippet: string | null;
  review_reason: string | null;
  extraction: JobEmailExtraction | null;
  matching_result: {
    decision?: string;
    confidence?: number;
    explanation?: string;
    method?: string;
    application_id?: string | null;
    candidate_application_ids?: string[];
  } | null;
  candidates: ApplicationSummary[];
};

export type ReviewActionResponse = {
  action: "mapped" | "created" | "dismissed";
  email_id: string;
  application: ApplicationSummary | null;
  status_update_id: string | null;
};

export type BackfillJobStatus = "pending" | "running" | "succeeded" | "failed";

export type BackfillJob = {
  id: string;
  user_id: string;
  start_date: string;
  status: BackfillJobStatus;
  gmail_query: string;
  page_token: string | null;
  fetched_count: number;
  saved_count: number;
  duplicate_count: number;
  processed_count: number;
  extracted_count: number;
  non_job_count: number;
  needs_review_count: number;
  failed_count: number;
  matched_count: number;
  created_count: number;
  errors: string[];
  last_error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BackfillStatus = {
  default_start_date: string;
  active_job: BackfillJob | null;
  latest_job: BackfillJob | null;
};

export const disconnectedStatus: AuthStatus = {
  authenticated: false,
  connected: false,
  email: null,
  monitored_email: null,
  gmail_watch: null,
};

export function googleOAuthStartUrl() {
  return `${API_BASE_URL}/auth/google/start`;
}

export async function fetchAuthStatus() {
  return apiFetch<AuthStatus>("/auth/status");
}

export async function logout() {
  return apiFetch<AuthStatus>("/auth/logout", {
    method: "POST",
  });
}

export async function fetchApplicationsOverview() {
  return apiFetch<ApplicationsOverview>("/applications/overview");
}

export async function fetchCompanyGroups() {
  return apiFetch<CompanyApplicationGroup[]>("/applications/company-groups");
}

export async function fetchApplicationDetail(applicationId: string) {
  return apiFetch<ApplicationDetail>(`/applications/${applicationId}`);
}

export async function updateApplicationStatus(
  applicationId: string,
  status: ApplicationStatus,
  explanation?: string,
) {
  return apiFetch<{
    application: ApplicationSummary;
    status_update_id: string;
  }>(`/applications/${applicationId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status, explanation }),
  });
}

export async function deleteApplication(applicationId: string) {
  return apiFetch<DeleteApplicationResponse>(`/applications/${applicationId}`, {
    method: "DELETE",
  });
}

export async function fetchReviewQueue() {
  return apiFetch<ReviewQueueItem[]>("/review/queue");
}

export async function mapReviewEmail(
  emailId: string,
  applicationId: string,
  status?: ApplicationStatus,
) {
  return apiFetch<ReviewActionResponse>(`/review/${emailId}/map`, {
    method: "POST",
    body: JSON.stringify({ application_id: applicationId, status }),
  });
}

export async function createApplicationFromReview(
  emailId: string,
  status?: ApplicationStatus,
) {
  return apiFetch<ReviewActionResponse>(
    `/review/${emailId}/create-application`,
    {
      method: "POST",
      body: JSON.stringify({ status }),
    },
  );
}

export async function dismissReviewEmail(emailId: string, reason?: string) {
  return apiFetch<ReviewActionResponse>(`/review/${emailId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function fetchBackfillStatus() {
  return apiFetch<BackfillStatus>("/backfill/status");
}

export async function startBackfill(startDate: string) {
  return apiFetch<BackfillJob>("/backfill/jobs", {
    method: "POST",
    body: JSON.stringify({ start_date: startDate }),
  });
}

export async function retryBackfill(jobId: string) {
  return apiFetch<BackfillJob>(`/backfill/jobs/${jobId}/retry`, {
    method: "POST",
  });
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error(await responseError(response));
  }

  return (await response.json()) as T;
}

async function responseError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String(item.msg)
            : String(item),
        )
        .join(" ");
    }
    return `Request failed with ${response.status}.`;
  } catch {
    return `Request failed with ${response.status}.`;
  }
}
