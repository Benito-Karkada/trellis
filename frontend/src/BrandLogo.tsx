import artwork from "./assets/trellis-classic.png";
import "./BrandLogo.css";

/** The approved artwork, arranged as a compact lockup without altering its pixels. */
export default function BrandLogo({large=false}:{large?:boolean}) {
  return <span className={`brand-logo${large ? " brand-logo-large" : ""}`} role="img" aria-label="Trellis">
    <svg className="brand-duck" viewBox="310 155 690 660" aria-hidden="true" focusable="false">
      <image href={artwork} width="1312" height="1199"/>
    </svg>
    <svg className="brand-wordmark" viewBox="195 835 900 290" aria-hidden="true" focusable="false">
      <image href={artwork} width="1312" height="1199"/>
    </svg>
  </span>;
}
