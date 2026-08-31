#include <bits/stdc++.h>
using namespace std;
int n;
bool f(int n){
	int sum=0;
	for(int i=1;i<n;i++){
		if(n%i==0)sum+=i;
	}
	if(sum==n)return true;
	return false;
}
int main()
{
	cin>>n;
	for(int i=2;i<=n;i++){
		if(f(i))cout<<i<<endl;
	}
}
