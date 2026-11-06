#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>

/* PNG 9.2 and 9.4, https://www.w3.org/TR/png-3/#9Filters.
 * Original implementation: score None, Up and Sub in one vectorizable pass,
 * then score Paeth using neighbor thresholds rather than three distances.
 * The Python caller owns compression, file format, metadata and cleanup.
 */
static unsigned int
distance(unsigned int value) {
    return value < 128 ? value : 256 - value;
}

static PyObject *
filter_rows(PyObject *self, PyObject *args) {
    const unsigned char *raw, *previous;
    Py_ssize_t length, prior_length, stride;
    if (!PyArg_ParseTuple(args, "y#y#n:filter_rows", &raw, &length,
                          &previous, &prior_length, &stride)) {
        return NULL;
    }
    if (stride < 4 || stride % 4 || prior_length != stride || length % stride) {
        PyErr_SetString(PyExc_ValueError, "Expected complete RGBA rows and one previous row");
        return NULL;
    }
    Py_ssize_t count = length / stride;
    if (count > PY_SSIZE_T_MAX - length || stride > PY_SSIZE_T_MAX / 3) {
        return PyErr_NoMemory();
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, length + count);
    if (!result) {
        return NULL;
    }
    unsigned char *scratch = PyMem_Malloc((size_t)stride * 3);
    if (!scratch) {
        Py_DECREF(result);
        return PyErr_NoMemory();
    }
    unsigned char *output = (unsigned char *)PyBytes_AS_STRING(result);
    unsigned char *up = scratch, *sub = scratch + stride, *paeth = scratch + 2 * stride;

    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t row = 0; row < count; row++) {
        const unsigned char *current = raw + row * stride;
        unsigned char *target = output + row * (stride + 1);
        if (memcmp(current, previous, (size_t)stride) == 0) {
            /* Equal rows have zero Up residual. A zero row ties with None. */
            unsigned char nonzero = 0;
            for (Py_ssize_t i = 0; i < stride; i++) {
                nonzero |= current[i];
            }
            target[0] = nonzero ? 2 : 0;
            memset(target + 1, 0, (size_t)stride);
        } else {
            /* Use wide scores: legal PNG rows can exceed a 32-bit sum. */
            unsigned long long none_score = 0, up_score = 0, sub_score = 0;
            for (Py_ssize_t i = 0; i < 4; i++) {
                unsigned int value = current[i];
                unsigned int u = (value - previous[i]) & 255;
                up[i] = (unsigned char)u;
                sub[i] = current[i];
                none_score += distance(value);
                up_score += distance(u);
                sub_score += distance(value);
            }
            for (Py_ssize_t i = 4; i < stride; i++) {
                unsigned int value = current[i];
                unsigned int u = (value - previous[i]) & 255;
                unsigned int s = (value - current[i - 4]) & 255;
                up[i] = (unsigned char)u;
                sub[i] = (unsigned char)s;
                none_score += distance(value);
                up_score += distance(u);
                sub_score += distance(s);
            }
            const unsigned char *best = current;
            unsigned long long best_score = none_score;
            unsigned char kind = 0;
            /* Strict ties and None/Up/Sub/Paeth order retain the old policy. */
            if (up_score < best_score) {
                best = up;
                best_score = up_score;
                kind = 2;
            }
            if (sub_score < best_score) {
                best = sub;
                best_score = sub_score;
                kind = 1;
            }
            if (best_score && stride > 4) {
                unsigned long long paeth_score = 0;
                for (Py_ssize_t i = 0; i < 4; i++) {
                    paeth[i] = up[i];
                    paeth_score += distance(up[i]);
                }
                for (Py_ssize_t i = 4; i < stride; i++) {
                    int a = current[i - 4], b = previous[i], c = previous[i - 4];
                    int low = a < b ? a : b, high = a > b ? a : b;
                    int total = a + b, triple = 3 * c;
                    int predictor = triple <= total + low ? high
                                  : triple >= total + high ? low : c;
                    unsigned int value = (current[i] - predictor) & 255;
                    paeth[i] = (unsigned char)value;
                    paeth_score += distance(value);
                }
                if (paeth_score < best_score) {
                    best = paeth;
                    kind = 4;
                }
            }
            target[0] = kind;
            memcpy(target + 1, best, (size_t)stride);
        }
        previous = current;
    }
    Py_END_ALLOW_THREADS
    PyMem_Free(scratch);
    return result;
}

static PyMethodDef methods[] = {
    {"filter_rows", filter_rows, METH_VARARGS,
     "Filter bounded RGBA row batches using signed-residual adaptive selection."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_png_filters", NULL, -1, methods
};

PyMODINIT_FUNC
PyInit__png_filters(void) {
    return PyModule_Create(&module);
}
