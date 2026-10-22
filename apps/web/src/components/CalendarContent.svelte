<script lang="ts">
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { DatePicker } from '@skeletonlabs/skeleton-svelte';

  import { i18n } from '%/useLocale.svelte.ts';

  // The popup calendar for a <DatePicker>, placed inside it: days, months and years, each
  // offered only when the picker's minView allows
  const ICON_SIZE = 16;
  const GRID_COLUMNS = 4;
</script>

{#snippet viewControl()}
  <DatePicker.ViewControl class="items-center">
    <DatePicker.PrevTrigger aria-label={i18n.t.dateField.previous}>
      <ChevronLeft aria-hidden="true" size={ICON_SIZE} />
    </DatePicker.PrevTrigger>
    <DatePicker.ViewTrigger>
      <DatePicker.RangeText />
    </DatePicker.ViewTrigger>
    <DatePicker.NextTrigger aria-label={i18n.t.dateField.next}>
      <ChevronRight aria-hidden="true" size={ICON_SIZE} />
    </DatePicker.NextTrigger>
  </DatePicker.ViewControl>
{/snippet}

<!-- The z-index sits on the content: the positioner copies it into an inline style of its own -->
<DatePicker.Positioner>
  <DatePicker.Content class="z-30 shadow-xl">
    <DatePicker.View view="day">
      <DatePicker.Context>
        {#snippet children(
          datePicker
        )}
          {@render viewControl()}
          <DatePicker.Table>
            <DatePicker.TableHead>
              <DatePicker.TableRow>
                {#each datePicker().weekDays as weekDay, index (index)}
                  <DatePicker.TableHeader>{weekDay.narrow}</DatePicker.TableHeader>
                {/each}
              </DatePicker.TableRow>
            </DatePicker.TableHead>
            <DatePicker.TableBody>
              {#each datePicker().weeks as week, index (index)}
                <DatePicker.TableRow>
                  {#each week as day (day.toString())}
                    <DatePicker.TableCell value={day}>
                      <DatePicker.TableCellTrigger>{day.day}</DatePicker.TableCellTrigger>
                    </DatePicker.TableCell>
                  {/each}
                </DatePicker.TableRow>
              {/each}
            </DatePicker.TableBody>
          </DatePicker.Table>
        {/snippet}
      </DatePicker.Context>
    </DatePicker.View>

    <DatePicker.View view="month">
      <DatePicker.Context>
        {#snippet children(
          datePicker
        )}
          {@render viewControl()}
          <DatePicker.Table>
            <DatePicker.TableBody>
              {#each datePicker().getMonthsGrid({
                columns: GRID_COLUMNS,
                format: 'short',
              }) as months, index (index)}
                <DatePicker.TableRow>
                  {#each months as month (month.value)}
                    <DatePicker.TableCell value={month.value}>
                      <DatePicker.TableCellTrigger>{month.label}</DatePicker.TableCellTrigger>
                    </DatePicker.TableCell>
                  {/each}
                </DatePicker.TableRow>
              {/each}
            </DatePicker.TableBody>
          </DatePicker.Table>
        {/snippet}
      </DatePicker.Context>
    </DatePicker.View>

    <DatePicker.View view="year">
      <DatePicker.Context>
        {#snippet children(
          datePicker
        )}
          {@render viewControl()}
          <DatePicker.Table>
            <DatePicker.TableBody>
              {#each datePicker().getYearsGrid({ columns: GRID_COLUMNS }) as years, index (index)}
                <DatePicker.TableRow>
                  {#each years as year (year.value)}
                    <DatePicker.TableCell value={year.value}>
                      <DatePicker.TableCellTrigger>{year.label}</DatePicker.TableCellTrigger>
                    </DatePicker.TableCell>
                  {/each}
                </DatePicker.TableRow>
              {/each}
            </DatePicker.TableBody>
          </DatePicker.Table>
        {/snippet}
      </DatePicker.Context>
    </DatePicker.View>
  </DatePicker.Content>
</DatePicker.Positioner>
