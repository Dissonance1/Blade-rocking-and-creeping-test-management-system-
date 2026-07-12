import {
  LayoutDashboard,
  Package,
  Settings,
  Bell,
  Moon,
  Boxes,
  MapPin,
  Wrench,
  BookOpen,
  FileText,
  FlaskConical,
  Users,
} from "lucide-react";

import { cn } from "@/utils/cn";

/**
 * Sidebar/navbar icons — thin wrappers around lucide-react so every nav icon
 * shares the same lined (stroke-only) style and stroke width as the rest of
 * the app, instead of a mix of hand-rolled filled and outline SVGs. Kept as
 * named exports matching the original custom-icon API so call sites
 * (`<DashboardIcon className="..." />`) don't need to change.
 */

interface IconProps {
  className?: string;
}

function iconCls(className?: string) {
  return cn("h-[1em] w-[1em]", className);
}

export function DashboardIcon({ className }: IconProps) {
  return <LayoutDashboard className={iconCls(className)} strokeWidth={1.75} />;
}

export function BatchOverviewIcon({ className }: IconProps) {
  return <Package className={iconCls(className)} strokeWidth={1.75} />;
}

export function SettingsIcon({ className }: IconProps) {
  return <Settings className={iconCls(className)} strokeWidth={1.75} />;
}

export function BellIcon({ className }: IconProps) {
  return <Bell className={iconCls(className)} strokeWidth={1.75} />;
}

export function MoonIcon({ className }: IconProps) {
  return <Moon className={iconCls(className)} strokeWidth={1.75} />;
}

export function AssemblyQueueIcon({ className }: IconProps) {
  return <Boxes className={iconCls(className)} strokeWidth={1.75} />;
}

export function SlotAllocationIcon({ className }: IconProps) {
  return <MapPin className={iconCls(className)} strokeWidth={1.75} />;
}

export function BladeEntryIcon({ className }: IconProps) {
  return <Wrench className={iconCls(className)} strokeWidth={1.75} />;
}

export function OhQueueIcon({ className }: IconProps) {
  return <BookOpen className={iconCls(className)} strokeWidth={1.75} />;
}

export function NotepadIcon({ className }: IconProps) {
  return <FileText className={iconCls(className)} strokeWidth={1.75} />;
}

export function RockingCreepIcon({ className }: IconProps) {
  return <FlaskConical className={iconCls(className)} strokeWidth={1.75} />;
}

export function UserManagementIcon({ className }: IconProps) {
  return <Users className={iconCls(className)} strokeWidth={1.75} />;
}
