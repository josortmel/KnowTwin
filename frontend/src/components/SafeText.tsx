import { safeText } from "../lib/render";

interface SafeTextProps {
  text: unknown;
  as?: keyof JSX.IntrinsicElements;
  className?: string;
}

export function SafeText({ text, as: Tag = "span", className }: SafeTextProps) {
  return <Tag className={className}>{safeText(text)}</Tag>;
}
