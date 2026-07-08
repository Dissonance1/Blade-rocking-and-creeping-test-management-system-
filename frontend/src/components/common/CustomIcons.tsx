import { cn } from "@/utils/cn";

/**
 * Hand-picked SVGs (mirrored under public/media/icons/) inlined here so they
 * pick up `currentColor` from Tailwind text-color utilities, same convention
 * as KTIcon. Size follows font-icon convention too — control via text-* on className.
 */

interface IconProps {
  className?: string;
}

export function DashboardIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M8.557 2.75H4.682A1.93 1.93 0 0 0 2.75 4.682v3.875a1.94 1.94 0 0 0 1.932 1.942h3.875a1.94 1.94 0 0 0 1.942-1.942V4.682A1.94 1.94 0 0 0 8.557 2.75m10.761 0h-3.875a1.94 1.94 0 0 0-1.942 1.932v3.875a1.943 1.943 0 0 0 1.942 1.942h3.875a1.94 1.94 0 0 0 1.932-1.942V4.682a1.93 1.93 0 0 0-1.932-1.932m0 10.75h-3.875a1.94 1.94 0 0 0-1.942 1.933v3.875a1.94 1.94 0 0 0 1.942 1.942h3.875a1.94 1.94 0 0 0 1.932-1.942v-3.875a1.93 1.93 0 0 0-1.932-1.932M8.557 13.5H4.682a1.943 1.943 0 0 0-1.932 1.943v3.875a1.93 1.93 0 0 0 1.932 1.932h3.875a1.94 1.94 0 0 0 1.942-1.932v-3.875a1.94 1.94 0 0 0-1.942-1.942"
      />
    </svg>
  );
}

export function BatchOverviewIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        fillRule="evenodd"
        clipRule="evenodd"
        d="M2.5 5.5v-3h3v3zM1 2a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1zm8 .25a.75.75 0 0 1 .75-.75h4.5a.75.75 0 0 1 0 1.5h-4.5A.75.75 0 0 1 9 2.25M9.75 5a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5zM2.5 10.5v3h3v-3zM2 9a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1v-4a1 1 0 0 0-1-1zm7.75.5a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5zm0 3.5a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5z"
      />
    </svg>
  );
}

export function SettingsIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="m9.25 22l-.4-3.2q-.325-.125-.612-.3t-.563-.375L4.7 19.375l-2.75-4.75l2.575-1.95Q4.5 12.5 4.5 12.338v-.675q0-.163.025-.338L1.95 9.375l2.75-4.75l2.975 1.25q.275-.2.575-.375t.6-.3l.4-3.2h5.5l.4 3.2q.325.125.613.3t.562.375l2.975-1.25l2.75 4.75l-2.575 1.95q.025.175.025.338v.674q0 .163-.05.338l2.575 1.95l-2.75 4.75l-2.95-1.25q-.275.2-.575.375t-.6.3l-.4 3.2zm2.8-6.5q1.45 0 2.475-1.025T15.55 12t-1.025-2.475T12.05 8.5q-1.475 0-2.488 1.025T8.55 12t1.013 2.475T12.05 15.5"
      />
    </svg>
  );
}

export function BellIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 5.365V3m0 2.365a5.34 5.34 0 0 1 5.133 5.368v1.8c0 2.386 1.867 2.982 1.867 4.175c0 .593 0 1.292-.538 1.292H5.538C5 18 5 17.301 5 16.708c0-1.193 1.867-1.789 1.867-4.175v-1.8A5.34 5.34 0 0 1 12 5.365M8.733 18c.094.852.306 1.54.944 2.112a3.48 3.48 0 0 0 4.646 0c.638-.572 1.236-1.26 1.33-2.112z"
      />
    </svg>
  );
}

export function MoonIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M21.64 13a1 1 0 0 0-1.05-.14a8.05 8.05 0 0 1-3.37.73a8.15 8.15 0 0 1-8.14-8.1a8.6 8.6 0 0 1 .25-2A1 1 0 0 0 8 2.36a10.14 10.14 0 1 0 14 11.69a1 1 0 0 0-.36-1.05m-9.5 6.69A8.14 8.14 0 0 1 7.08 5.22v.27a10.15 10.15 0 0 0 10.14 10.14a9.8 9.8 0 0 0 2.1-.22a8.11 8.11 0 0 1-7.18 4.32Z"
      />
    </svg>
  );
}

export function AssemblyQueueIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M3 6c-.55 0-1 .45-1 1v13c0 1.1.9 2 2 2h13c.55 0 1-.45 1-1s-.45-1-1-1H5c-.55 0-1-.45-1-1V7c0-.55-.45-1-1-1m17-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2m-2 9h-3v3c0 .55-.45 1-1 1s-1-.45-1-1v-3h-3c-.55 0-1-.45-1-1s.45-1 1-1h3V6c0-.55.45-1 1-1s1 .45 1 1v3h3c.55 0 1 .45 1 1s-.45 1-1 1"
      />
    </svg>
  );
}

export function SlotAllocationIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M5 22q-.825 0-1.412-.587T3 20V6q0-.825.588-1.412T5 4h1V2h2v2h8V2h2v2h1q.825 0 1.413.588T21 6v4.675q0 .425-.288.713t-.712.287t-.712-.288t-.288-.712V10H5v10h5.8q.425 0 .713.288T11.8 21t-.288.713T10.8 22zm9.463-.462Q13 20.075 13 18t1.463-3.537T18 13t3.538 1.463T23 18t-1.463 3.538T18 23t-3.537-1.463m5.212-1.162l.7-.7L18.5 17.8V15h-1v3.2z"
      />
    </svg>
  );
}

export function BladeEntryIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path fill="currentColor" d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.5 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/>
    </svg>
  );
}

export function OhQueueIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M5.616 21q-.672 0-1.144-.472T4 19.385V8.263q-.43-.178-.715-.577Q3 7.286 3 6.769V4.615q0-.67.472-1.143Q3.944 3 4.616 3h14.769q.67 0 1.143.472q.472.472.472 1.144v2.153q0 .517-.285.916q-.284.4-.715.578v11.122q0 .67-.472 1.143q-.472.472-1.143.472zM5 8.385v10.904q0 .307.221.509T5.77 20h12.616q.269 0 .442-.173t.173-.442v-11zm-.385-1h14.77q.269 0 .442-.173T20 6.769V4.616q0-.27-.173-.443T19.384 4H4.616q-.27 0-.443.173T4 4.616v2.153q0 .27.173.442q.173.173.443.173m4.769 5.482h5.23V12h-5.23zM12 14.192"
      />
    </svg>
  );
}

export function NotepadIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M7.5 7a.5.5 0 0 0 0 1h5a.5.5 0 0 0 0-1zM7 10.5a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1-.5-.5m.5 2.5a.5.5 0 0 0 0 1h2a.5.5 0 0 0 0-1zm-1-11a.5.5 0 0 0-.5.5V3h-.5A1.5 1.5 0 0 0 4 4.5v12A1.5 1.5 0 0 0 5.5 18h6a.5.5 0 0 0 .354-.146l4-4A.5.5 0 0 0 16 13.5v-9A1.5 1.5 0 0 0 14.5 3H14v-.5a.5.5 0 0 0-1 0V3h-2.5v-.5a.5.5 0 0 0-1 0V3H7v-.5a.5.5 0 0 0-.5-.5m8 2a.5.5 0 0 1 .5.5V13h-2.5a1.5 1.5 0 0 0-1.5 1.5V17H5.5a.5.5 0 0 1-.5-.5v-12a.5.5 0 0 1 .5-.5zm-.207 10L12 16.293V14.5a.5.5 0 0 1 .5-.5z"
      />
    </svg>
  );
}

export function RockingCreepIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M5 19q-.846 0-1.423-.577T3 17t.577-1.423T5 15h14q.846 0 1.423.577T21 17t-.577 1.423T19 19zm0-1h14q.425 0 .713-.288T20 17t-.288-.712T19 16H5q-.425 0-.712.288T4 17t.288.713T5 18m6.761-5q-.34 0-.57-.23t-.23-.57V5.8q0-.34.23-.57t.57-.23h6.401q.34 0 .57.23t.23.57v6.4q0 .34-.23.57t-.57.23zm.2-1h6V6h-6zM3 11.489v-.983h5.944v.983zM12.962 8.5h4v-.994h-4zM5 8.5h3.944v-.994H5zm6.962 3.5V6z"
      />
    </svg>
  );
}

export function UserManagementIcon({ className }: IconProps) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" className={cn("h-[1em] w-[1em]", className)}>
      <path
        fill="currentColor"
        d="M15 20H9a3 3 0 0 0-3 3v2h2v-2a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2h2v-2a3 3 0 0 0-3-3m-3-1a4 4 0 1 0-4-4a4 4 0 0 0 4 4m0-6a2 2 0 1 1-2 2a2 2 0 0 1 2-2"
      />
      <path
        fill="currentColor"
        d="M28 19v9H4V8h12V6H4a2 2 0 0 0-2 2v20a2 2 0 0 0 2 2h24a2 2 0 0 0 2-2v-9Z"
      />
      <path
        fill="currentColor"
        d="M20 19h6v2h-6zm2 4h4v2h-4zm10-13V8h-2.101a5 5 0 0 0-.732-1.753l1.49-1.49l-1.414-1.414l-1.49 1.49A5 5 0 0 0 26 4.101V2h-2v2.101a5 5 0 0 0-1.753.732l-1.49-1.49l-1.414 1.414l1.49 1.49A5 5 0 0 0 20.101 8H18v2h2.101a5 5 0 0 0 .732 1.753l-1.49 1.49l1.414 1.414l1.49-1.49a5 5 0 0 0 1.753.732V16h2v-2.101a5 5 0 0 0 1.753-.732l1.49 1.49l1.414-1.414l-1.49-1.49A5 5 0 0 0 29.899 10Zm-7 2a3 3 0 1 1 3-3a3.003 3.003 0 0 1-3 3"
      />
    </svg>
  );
}
