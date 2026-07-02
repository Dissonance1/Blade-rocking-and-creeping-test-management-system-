import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { cn } from "@/utils/cn";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  breadcrumb?: BreadcrumbItem[];
}

export default function PageHeader({
  title,
  subtitle,
  actions,
  breadcrumb,
}: PageHeaderProps) {
  return (
    <div className="mb-6">
      {/* Breadcrumb */}
      {breadcrumb && breadcrumb.length > 0 && (
        <nav
          aria-label="Breadcrumb"
          className="flex items-center gap-1 text-sm text-muted-foreground mb-2 flex-wrap"
        >
          {breadcrumb.map((item, index) => {
            const isLast = index === breadcrumb.length - 1;
            return (
              <span key={index} className="flex items-center gap-1">
                {index > 0 && (
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60 flex-shrink-0" />
                )}
                {item.href && !isLast ? (
                  <Link
                    to={item.href}
                    className="hover:text-foreground transition-colors hover:underline underline-offset-2"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span
                    className={cn(
                      isLast ? "text-foreground font-medium" : ""
                    )}
                  >
                    {item.label}
                  </span>
                )}
              </span>
            );
          })}
        </nav>
      )}

      {/* Title row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-foreground truncate">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>

        {actions && (
          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
