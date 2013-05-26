import numpy as np
from pycuda import gpuarray
from pycuda.compiler import SourceModule

code = """
__global__ void addRowVecToMat(float *mat, float *vec, float *target, int32_t n, int32_t m)
{
  int tx = blockIdx.x * blockDim.x + threadIdx.x;
  int ty = blockIdx.y * blockDim.y + threadIdx.y;
   
  if ((ty < m) & (tx < n))
  {
      target[tx*m+ty] = vec[ty] + mat[tx*m+ty];
  }
}

__global__ void addColVecToMat(float *mat, float *vec, float *target, int32_t n, int32_t m)
{
  int tx = blockIdx.x * blockDim.x + threadIdx.x;
  int ty = blockIdx.y * blockDim.y + threadIdx.y;
   
  if ((ty < m) & (tx < n))
  {
      target[tx*m+ty] = vec[tx] + mat[tx*m+ty];
  }
}

__global__ void kVectorNormalize(float* mat, float max_vec_norm, 
    unsigned int width, unsigned int height) {
    
    __shared__ float sum_shared[32];
    __shared__ float vec_norm;
    float sum = 0;
 
    for (unsigned int i = threadIdx.x; i < height; i += 32)
        sum += powf(mat[blockIdx.x + i * width], 2);

    sum_shared[threadIdx.x] = sum;

    __syncthreads();

    if (threadIdx.x == 0) {
        sum = 0;

        for (unsigned int i = 0; i < 32; i++)
            sum += sum_shared[i];

        vec_norm = sqrtf(sum);
    }
    __syncthreads();

    for (unsigned int i = threadIdx.x; i < height; i += 32) {
        if (vec_norm > max_vec_norm)
            mat[blockIdx.x + i * width] /= (vec_norm / max_vec_norm);
    }
}
"""

mod = SourceModule(code)
add_row_vec_kernel = mod.get_function('addRowVecToMat')
add_col_vec_kernel = mod.get_function('addColVecToMat')
vector_normalize_kernel = mod.get_function("kVectorNormalize")

def add_vec_to_mat(mat, vec, axis=None, inplace=False):
    """ Add a vector to a matrix
    """
    
    if axis is None:
        if vec.shape[0] == mat.shape[0]: 
            axis = 0
        elif vec.shape[0] == mat.shape[1]:
            axis = 1
        else:
            raise ValueError('Vector length must be equal to one side of the matrix')            
    
    n, m = mat.shape
    
    block = (12, 12, 1)
    gridx = n // block[0] + 1 * (n % block[0] != 0)
    gridy = m // block[1] + 1 * (m % block[1] != 0)
    grid = (gridx, gridy, 1)

    if inplace:
        target = mat
    else:
        target = gpuarray.empty_like(mat)
    
    if axis == 0:
        assert vec.shape[0] == mat.shape[0]
        add_col_vec_kernel(mat, vec, target, np.uint32(n), np.uint32(m),
                           block=block, grid=grid)
    elif axis == 1:
        assert vec.shape[0] == mat.shape[1]
        add_row_vec_kernel(mat, vec, target, np.uint32(n), np.uint32(m),
                           block=block, grid=grid)
    return target

def vector_normalize(mat, max_vec_norm=1.):
    """ Normalize each column vector in mat to length max_vec_norm if it is longer than
    max_vec_norm
    """
    n,m = mat.shape
    
    vector_normalize_kernel(mat, np.float32(max_vec_norm), 
                            np.int32(m), np.int32(n), block=(32,1,1), grid=(m,1,1))