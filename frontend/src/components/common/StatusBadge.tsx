import type { BladeStatus } from "@/types";
import { cn } from "@/utils/cn";

interface StatusConfig {
  label: string;
  classes: string;
}

const STATUS_MAP: Record<BladeStatus, StatusConfig> = {
  CREATED: {
    label: "Created",
    classes: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800",
  },
  OH_INSPECTION: {
    label: "OH Inspection",
    classes: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
  },
  MEASUREMENTS_RECORDED: {
    label: "Measurements Recorded",
    classes: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
  },
  SENT_TO_ASSEMBLY: {
    label: "Sent to Assembly",
    classes: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
  },
  SLOT_ASSIGNED: {
    label: "Slot Assigned",
    classes: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800",
  },
  BALANCING_IN_PROGRESS: {
    label: "Balancing In Progress",
    classes: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
  },
  BALANCING_COMPLETED: {
    label: "Balancing Completed",
    classes: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
  },
  RETURNED_TO_OH: {
    label: "Returned to OH",
    classes: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
  },
  FINAL_VERIFICATION: {
    label: "Final Verification",
    classes: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800",
  },
  COMPLETED: {
    label: "Completed",
    classes: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
  },
  REJECTED: {
    label: "Rejected",
    classes: "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800",
  },
  ON_HOLD: {
    label: "On Hold",
    classes: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800",
  },
  REOPENED: {
    label: "Reopened",
    classes: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800",
  },
};

const SIZE_CLASSES = {
  sm: "text-xs px-1.5 py-0.5",
  md: "text-sm px-2.5 py-0.5",
  lg: "text-base px-3 py-1",
};

interface StatusBadgeProps {
  status: BladeStatus;
  size?: "sm" | "md" | "lg";
}

export default function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? {
    label: status,
    classes: "bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center font-medium rounded-full border whitespace-nowrap",
        SIZE_CLASSES[size],
        config.classes
      )}
    >
      {config.label}
    </span>
  );
}
