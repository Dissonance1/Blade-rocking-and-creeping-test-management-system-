export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="py-1 text-xs text-slate-400 dark:text-slate-500 text-center w-full">
      &copy; {year} Meridian Data Labs
    </footer>
  );
}
