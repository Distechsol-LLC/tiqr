type PluralForms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };

const rules = new Map<string, Intl.PluralRules>();

// The form a count takes in a language: Russian has one, few and many where English has one and other
export const plural = (locale: string, count: number, forms: PluralForms): string => {
  let rule = rules.get(locale);

  if (!rule) {
    rule = new Intl.PluralRules(locale);
    rules.set(locale, rule);
  }

  return forms[rule.select(count)] ?? forms.other;
};
