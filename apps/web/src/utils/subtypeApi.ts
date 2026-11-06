import { z } from 'zod';

import { type ApiResult, request, write } from '%/api.ts';
import { type VisitorSubtype, type VisitorSubtypeFields, visitorSubtypeSchema } from '$/catalog.ts';

// A ticket mode visitor type's subtypes, which tickets are issued for; badges have none
const createVisitorSubtype = (
  csrfToken: string,
  typeId: string,
  fields: VisitorSubtypeFields
): Promise<ApiResult<VisitorSubtype>> =>
  request(
    `/visitor-types/${typeId}/subtypes`,
    visitorSubtypeSchema,
    write('POST', csrfToken, fields)
  );

const updateVisitorSubtype = (
  csrfToken: string,
  typeId: string,
  id: string,
  fields: Partial<VisitorSubtypeFields>
): Promise<ApiResult<VisitorSubtype>> =>
  request(
    `/visitor-types/${typeId}/subtypes/${id}`,
    visitorSubtypeSchema,
    write('PATCH', csrfToken, fields)
  );

// Tickets already issued keep their name and discount
const deleteVisitorSubtype = (
  csrfToken: string,
  typeId: string,
  id: string
): Promise<ApiResult<null>> =>
  request(`/visitor-types/${typeId}/subtypes/${id}`, z.null(), write('DELETE', csrfToken));

export { createVisitorSubtype, deleteVisitorSubtype, updateVisitorSubtype };
