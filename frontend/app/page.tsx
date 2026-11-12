export default function FoundationPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl items-center px-6 py-16 sm:px-10">
      <section
        aria-labelledby="foundation-heading"
        className="w-full rounded-3xl border border-black/10 bg-white/90 p-8 shadow-[0_24px_80px_rgb(23_107_85_/_0.10)] sm:p-12"
      >
        <p className="mb-5 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-800">
          Foundation ready
        </p>
        <h1
          id="foundation-heading"
          className="max-w-3xl text-4xl font-semibold tracking-tight text-neutral-950 sm:text-6xl"
        >
          AI Marketing Report Assistant
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-8 text-neutral-600">
          The application workspace is set up for local development. Product report controls will
          arrive in their approved implementation stages.
        </p>
        <dl className="mt-10 grid gap-4 sm:grid-cols-3" aria-label="Foundation status">
          {[
            ["Frontend", "Configured"],
            ["Backend", "Health-ready"],
            ["Local services", "Documented"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl bg-neutral-100 p-5">
              <dt className="text-sm text-neutral-600">{label}</dt>
              <dd className="mt-1 font-semibold text-neutral-950">{value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  );
}

