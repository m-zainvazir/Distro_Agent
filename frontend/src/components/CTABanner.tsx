interface CTABannerProps {
  totalStores: number
}

export default function CTABanner({ totalStores }: CTABannerProps) {
  const calendlyUrl =
    process.env.NEXT_PUBLIC_CALENDLY_URL ?? 'https://calendly.com/distroagent'

  return (
    <div
      className="rounded-2xl p-12 text-white text-center mt-8"
      style={{ backgroundColor: '#7C9A82' }}
    >
      <h2
        className="font-display mb-4 leading-snug"
        style={{ fontSize: 32, fontWeight: 400 }}
      >
        Want us to pitch all {totalStores} boutiques for you?
      </h2>

      <p
        className="text-base leading-relaxed mb-8 mx-auto max-w-sm"
        style={{ color: 'rgba(255,255,255,0.85)' }}
      >
        Our team will send hyper-personalized outreach to every matched store —
        and handle the negotiations.
      </p>

      <a
        href={calendlyUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 bg-white px-8 h-[52px] rounded-sm
                   text-sage-dark font-semibold text-base transition-colors duration-150
                   hover:bg-[#F5F5F5]"
      >
        Book a Free Strategy Call →
      </a>

      <p
        className="text-sm mt-5"
        style={{ color: 'rgba(255,255,255,0.7)' }}
      >
        ✦ Done-for-you · No templates · Real relationships
      </p>
    </div>
  )
}
