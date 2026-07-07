export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="mt-6 text-xs text-slate-400 dark:text-slate-500">
      {year}&copy; Meridian Data Labs
    </footer>
  );
}
