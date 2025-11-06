import { useEffect, useRef } from 'react';
import { Controller, useForm } from 'react-hook-form';
import type { ParamSchema } from '@/types/settings';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { stableHash } from '@/lib/equality';

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) && !(value instanceof Date);

const clonePlain = <T,>(value: T): T => {
  if (Array.isArray(value)) {
    return value.map((item) => clonePlain(item)) as unknown as T;
  }
  if (value instanceof Date) {
    return new Date(value.getTime()) as unknown as T;
  }
  if (isPlainObject(value)) {
    const entries: Record<string, unknown> = {};
    for (const key of Object.keys(value)) {
      entries[key] = clonePlain(value[key]);
    }
    return entries as unknown as T;
  }
  return value;
};

type DynamicParamFormProps = {
  schema: ParamSchema;
  initial?: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  submitLabel?: string;
  onChange?: (values: Record<string, unknown>) => void;
};

export function DynamicParamForm({
  schema,
  initial,
  onSubmit,
  submitLabel = 'Save',
  onChange,
}: DynamicParamFormProps) {
  const defaults = Object.fromEntries(
    schema.fields.map((field) => [
      field.key,
      initial?.[field.key] ??
        ('default' in field ? field.default : field.type === 'boolean' ? false : ''),
    ]),
  );

  const { control, handleSubmit, watch } = useForm({ defaultValues: defaults });

  const watchedValues = watch();
  const lastHash = useRef<string | null>(null);

  useEffect(() => {
    if (!onChange) {
      return;
    }
    const nextHash = stableHash(watchedValues);
    if (lastHash.current === nextHash) {
      return;
    }
    lastHash.current = nextHash;
    onChange(clonePlain(watchedValues));
  }, [watchedValues, onChange]);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      {schema.fields.map((field) => (
        <div key={field.key} className="grid gap-2">
          <Label htmlFor={field.key}>{field.label}</Label>

          {field.type === 'boolean' && (
            <Controller
              name={field.key}
              control={control}
              render={({ field: controllerField }) => (
                <Switch
                  id={field.key}
                  checked={Boolean(controllerField.value)}
                  onCheckedChange={controllerField.onChange}
                />
              )}
            />
          )}

          {field.type === 'string' && (
            <Controller
              name={field.key}
              control={control}
              render={({ field: controllerField }) => (
                <Input id={field.key} placeholder={field.placeholder} {...controllerField} />
              )}
            />
          )}

          {(field.type === 'number' || field.type === 'integer') && (
            <Controller
              name={field.key}
              control={control}
              render={({ field: controllerField }) => (
                <div className="flex items-center gap-3">
                  <Input
                    id={field.key}
                    type="number"
                    step={field.step ?? (field.type === 'integer' ? 1 : 0.1)}
                    {...controllerField}
                  />
                  {field.min !== undefined && field.max !== undefined && (
                    <Slider
                      className="w-44"
                      min={field.min}
                      max={field.max}
                      step={field.step ?? (field.type === 'integer' ? 1 : 0.1)}
                      value={[Number(controllerField.value ?? field.default ?? field.min)]}
                      onValueChange={([value]) => controllerField.onChange(value)}
                    />
                  )}
                </div>
              )}
            />
          )}

          {field.type === 'select' && (
            <Controller
              name={field.key}
              control={control}
              render={({ field: controllerField }) => (
                <Select value={controllerField.value as string} onValueChange={controllerField.onChange}>
                  <SelectTrigger id={field.key}>
                    <SelectValue placeholder="Select" />
                  </SelectTrigger>
                  <SelectContent>
                    {(field.options ?? []).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          )}

          {'hint' in field && field.hint && (
            <p className="text-xs text-muted-foreground">{field.hint}</p>
          )}
        </div>
      ))}
      <div className="pt-2">
        <Button type="submit">{submitLabel}</Button>
      </div>
    </form>
  );
}
